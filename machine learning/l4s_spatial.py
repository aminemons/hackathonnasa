"""Train CUDA U-Nets and select by validation AP before touching held-out test."""
import argparse
import hashlib
import json
from pathlib import Path
import time

import numpy as np
from sklearn.metrics import average_precision_score, precision_recall_curve
import torch
from torch import nn
from torch.nn import functional as F


class ConvBlock(nn.Module):
    def __init__(self, inputs, outputs):
        super().__init__()
        self.layers = nn.Sequential(
            nn.Conv2d(inputs, outputs, 3, padding=1, bias=False),
            nn.GroupNorm(8, outputs), nn.SiLU(inplace=True),
            nn.Conv2d(outputs, outputs, 3, padding=1, bias=False),
            nn.GroupNorm(8, outputs),
        )
        self.skip = nn.Conv2d(inputs, outputs, 1) if inputs != outputs else nn.Identity()

    def forward(self, x):
        return F.silu(self.layers(x) + self.skip(x))


class SpatialModel(nn.Module):
    def __init__(self, width, mean, std, dropout):
        super().__init__()
        self.register_buffer("mean", mean.reshape(1, 14, 1, 1))
        self.register_buffer("std", std.reshape(1, 14, 1, 1))
        self.encoder1 = ConvBlock(14, width)
        self.encoder2 = ConvBlock(width, width * 2)
        self.encoder3 = ConvBlock(width * 2, width * 4)
        self.center = nn.Sequential(ConvBlock(width * 4, width * 6), nn.Dropout2d(dropout))
        self.decoder3 = ConvBlock(width * 10, width * 3)
        self.decoder2 = ConvBlock(width * 5, width * 2)
        self.decoder1 = ConvBlock(width * 3, width)
        self.out = nn.Conv2d(width, 1, 1)

    @staticmethod
    def up(x, skip):
        return torch.cat((F.interpolate(x, scale_factor=2, mode="bilinear", align_corners=False), skip), dim=1)

    def forward(self, x):
        x = torch.where(torch.isfinite(x), x, self.mean)
        x = ((x - self.mean) / self.std).clamp(-8, 8)
        a = self.encoder1(x)
        b = self.encoder2(F.max_pool2d(a, 2))
        c = self.encoder3(F.max_pool2d(b, 2))
        middle = self.center(F.max_pool2d(c, 2))
        x = self.decoder3(self.up(middle, c))
        x = self.decoder2(self.up(x, b))
        x = self.decoder1(self.up(x, a))
        return self.out(x)


def read_manifest(path):
    return json.loads((path / "manifest.json").read_text())


def load(data, split, device):
    ids = read_manifest(data)["chip_ids"][split]
    x = np.empty((len(ids), 128, 128, 14), dtype=np.float32)
    y = np.empty((len(ids), 1, 128, 128), dtype=np.uint8)
    for i, index in enumerate(ids):
        with np.load(data / split / f"{index}.npz") as tile:
            x[i], y[i, 0] = tile["x"], tile["y"]
    return (
        torch.from_numpy(x).permute(0, 3, 1, 2).to(device),
        torch.from_numpy(y).to(device=device, dtype=torch.float32),
    )


def normalization_images(x):
    sparse = x[:, :, ::8, ::8].permute(1, 0, 2, 3).reshape(14, -1).cpu().numpy()
    sparse = np.where(np.isfinite(sparse), sparse, np.nan)
    low, center, high = np.nanpercentile(sparse, [2, 50, 98], axis=1)
    return torch.tensor(center, dtype=torch.float32), torch.tensor(np.maximum((high - low) / 4, 1e-4), dtype=torch.float32)


def spatial_loss(logits, y):
    logits = logits.float()
    score = logits.sigmoid()
    bce = F.binary_cross_entropy_with_logits(logits, y, pos_weight=y.new_tensor(3.0), reduction="none")
    focal = (bce * (score - y).abs().pow(1.4)).mean()
    overlap = (score * y).sum()
    dice = 1 - (2 * overlap + 1) / (score.sum() + y.sum() + 1)
    return 0.55 * focal + 0.45 * dice


def augment(x, y, rng):
    rotation = int(rng.integers(4))
    x = torch.rot90(x, rotation, (-2, -1))
    y = torch.rot90(y, rotation, (-2, -1))
    if rng.random() < 0.5:
        x, y = x.flip(-1), y.flip(-1)
    return x.contiguous(memory_format=torch.channels_last), y


@torch.inference_mode()
def probabilities(model, x):
    model.eval()
    outputs = []
    for batch in x.split(16):
        batch = batch.contiguous(memory_format=torch.channels_last)
        with torch.autocast("cuda", dtype=torch.bfloat16):
            logits = model(batch)
        outputs.append(logits.float().sigmoid().cpu().numpy())
    return np.concatenate(outputs).reshape(-1)


def scores(y, prob, threshold=None):
    y = y.reshape(-1).cpu().numpy().astype(np.uint8)
    if threshold is None:
        precision, recall, thresholds = precision_recall_curve(y, prob)
        sums = precision[:-1] + recall[:-1]
        f = np.divide(2 * precision[:-1] * recall[:-1], sums, out=np.zeros_like(sums), where=sums != 0)
        threshold = float(thresholds[np.argmax(f)])
    selected = prob >= threshold
    tp = int(np.count_nonzero(selected & (y == 1)))
    fp = int(selected.sum()) - tp
    fn = int(y.sum()) - tp
    return {
        "threshold": threshold, "average_precision": float(average_precision_score(y, prob)),
        "f1": 2 * tp / max(1, 2 * tp + fp + fn), "precision": tp / max(1, tp + fp),
        "recall": tp / max(1, tp + fn), "positive_pixels": int(y.sum()), "reviewed_pixels": len(y),
    }


def train(args):
    device = torch.device("cuda", args.device)
    torch.cuda.set_device(device)
    torch.backends.cudnn.benchmark = True
    torch.set_float32_matmul_precision("high")
    torch.manual_seed(args.seed)
    rng = np.random.default_rng(args.seed)
    x, y = load(args.data, "train", device)
    xv, yv = load(args.data, "validation", device)
    center, std = normalization_images(x)
    model = SpatialModel(args.width, center, std, args.dropout).to(device, memory_format=torch.channels_last)
    optimizer = torch.optim.AdamW(model.parameters(), lr=0.0012, weight_decay=0.001, fused=True)
    scheduler = torch.optim.lr_scheduler.OneCycleLR(
        optimizer, max_lr=0.0012, total_steps=args.epochs * (len(x) // args.batch),
        pct_start=0.14, div_factor=9, final_div_factor=18,
    )
    positive = np.flatnonzero(y.sum(dim=(1, 2, 3)).cpu().numpy() >= 12)
    best, best_epoch = -1.0, 0
    start = time.monotonic()
    counts = read_manifest(args.data)["chip_ids"]
    manifest_hash = hashlib.sha256((args.data / "manifest.json").read_bytes()).hexdigest()
    trainer_hash = hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    training_signature = {
        "width": args.width, "batch": args.batch, "epochs": args.epochs,
        "seed": args.seed, "dropout": args.dropout,
        "manifest_sha256": manifest_hash, "trainer_sha256": trainer_hash,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    for epoch in range(1, args.epochs + 1):
        model.train()
        shuffled = rng.permutation(len(x))
        if epoch % 3 == 0:
            oversample = len(shuffled) // 6
            shuffled[:oversample] = rng.choice(positive, oversample, replace=True)
        running = torch.zeros((), device=device)
        for indices in np.split(shuffled[:len(x) // args.batch * args.batch], len(x) // args.batch):
            xb, yb = augment(x[indices], y[indices], rng)
            optimizer.zero_grad(set_to_none=True)
            with torch.autocast("cuda", dtype=torch.bfloat16):
                logits = model(xb)
                loss = spatial_loss(logits, yb)
            loss.backward()
            nn.utils.clip_grad_norm_(model.parameters(), 2.0)
            optimizer.step()
            scheduler.step()
            running += loss.detach()
        if epoch != 1 and epoch != args.epochs and epoch % 2:
            continue
        val = scores(yv, probabilities(model, xv))
        print(json.dumps({"gpu": args.device, "epoch": epoch, "loss": float(running / (len(x) // args.batch)),
                          "val_ap": val["average_precision"], "val_f1": val["f1"],
                          "seconds": round(time.monotonic() - start, 1)}), flush=True)
        if val["average_precision"] > best:
            best = val["average_precision"]
            best_epoch = epoch
            target = args.output / "model.pt"
            torch.save({"width": args.width, "state": model.state_dict(), "validation": val, "epoch": epoch,
                        "seed": args.seed, "device": torch.cuda.get_device_name(device),
                        "chips": {part: len(ids) for part, ids in counts.items()},
                        "training_signature": training_signature}, target.with_suffix(".tmp"))
            target.with_suffix(".tmp").replace(target)
        if epoch - best_epoch >= 12 and epoch >= 24:
            break


class ProbabilityModel(nn.Module):
    def __init__(self, members):
        super().__init__()
        self.members = nn.ModuleList(members)

    def forward(self, x):
        return torch.stack([model(x).sigmoid() for model in self.members]).mean(dim=0)


def restore(path, device):
    checkpoint = torch.load(path, map_location="cpu", weights_only=True)
    state = checkpoint["state"]
    model = SpatialModel(checkpoint["width"], state["mean"], state["std"], 0).to(device, memory_format=torch.channels_last)
    model.load_state_dict(state)
    return model.eval(), {key: value for key, value in checkpoint.items() if key != "state"}


@torch.inference_mode()
def serve_probs(model, x):
    return np.concatenate([model(batch).cpu().numpy() for batch in x.split(12)]).reshape(-1)


def select(args):
    import onnxruntime as ort

    device = torch.device("cuda", args.device)
    torch.set_float32_matmul_precision("highest")
    members = [restore(path, device) for path in args.checkpoints]
    xv, yv = load(args.data, "validation", device)
    options = [(i,) for i in range(len(members))]
    if len(members) > 1:
        options.append(tuple(range(len(members))))
    results = []
    for indices in options:
        model = ProbabilityModel([members[index][0] for index in indices]).eval()
        validation = scores(yv, serve_probs(model, xv))
        results.append((validation["average_precision"] - 0.003 * (len(indices) - 1), indices, validation))
    _, indices, validation = max(results)
    model = ProbabilityModel([members[index][0] for index in indices]).eval()
    xt, yt = load(args.data, "test", device)
    test = scores(yt, serve_probs(model, xt), validation["threshold"])
    args.output.mkdir(parents=True, exist_ok=True)
    model = model.cpu().eval()
    example = xt[:1].cpu().contiguous()
    target = args.output / "landslide_spatial.onnx"
    torch.onnx.export(model, (example,), target, input_names=["tile"], output_names=["scores"],
                      opset_version=17, dynamo=False)
    session = ort.InferenceSession(str(target), providers=["CPUExecutionProvider"])
    predicted = session.run(["scores"], {"tile": example.numpy()})[0]
    with torch.inference_mode():
        reference = model(example).numpy()
    np.testing.assert_allclose(predicted, reference, rtol=1e-4, atol=2e-5)
    report = {"revision": read_manifest(args.data)["revision"], "validation": validation, "test": test,
              "candidates": [record for _, record in members], "selected": list(indices),
              "onnx_max_abs_error": float(np.max(abs(predicted - reference))),
              "precision": "CUDA BF16 training; float32 exported inference",
              "chip_ids": read_manifest(args.data)["chip_ids"]}
    (args.output / "spatial-metrics.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps({key: value for key, value in report.items() if key != "chip_ids"}), flush=True)


def main():
    parser = argparse.ArgumentParser()
    commands = parser.add_subparsers(dest="command", required=True)
    training = commands.add_parser("train")
    evaluation = commands.add_parser("select")
    for command in (training, evaluation):
        command.add_argument("--data", type=Path, required=True)
        command.add_argument("--output", type=Path, required=True)
        command.add_argument("--device", type=int, required=True)
    training.add_argument("--width", type=int, required=True)
    training.add_argument("--batch", type=int, required=True)
    training.add_argument("--epochs", type=int, default=42)
    training.add_argument("--seed", type=int, required=True)
    training.add_argument("--dropout", type=float, required=True)
    evaluation.add_argument("--checkpoints", type=Path, nargs="+", required=True)
    args = parser.parse_args()
    train(args) if args.command == "train" else select(args)


if __name__ == "__main__":
    main()
