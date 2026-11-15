"""Post-event scar screening: NOT a landslide danger or exposure model.

The ONNX model estimates where scar-like pixels may exist *after* an event.
These tiers are transparent review queues based only on contiguous predicted
pixel counts. They do not estimate future failure, slope stability, affected
population, or infrastructure exposure. Never interpret a low/none tier as safe.
"""
from collections import deque
from math import isfinite


MIN_REVIEW_COMPONENT_PIXELS = 6
MEDIUM_COMPONENT_PIXELS = 24
HIGH_COMPONENT_PIXELS = 128


def assess(scores, width, height, threshold):
    """Describe connected scar candidates without pretending to infer danger."""
    if len(scores) != width * height:
        raise ValueError("Score dimensions do not match image dimensions")
    if not isfinite(float(threshold)) or not 0 <= threshold <= 1:
        raise ValueError("Invalid model threshold")
    valid = [v is not None and isfinite(float(v)) for v in scores]
    active = [ok and float(score) >= threshold for ok, score in zip(valid, scores)]
    seen = bytearray(width * height)
    components = []
    for start, present in enumerate(active):
        if not present or seen[start]:
            continue
        seen[start] = 1
        queue = deque([start])
        count = 0
        peak = 0.0
        sum_score = 0.0
        minrow = height
        mincol = width
        maxrow = maxcol = 0
        while queue:
            pixel = queue.popleft()
            row, col = divmod(pixel, width)
            count += 1
            confidence = float(scores[pixel])
            sum_score += confidence
            peak = max(peak, confidence)
            minrow, maxrow = min(minrow, row), max(maxrow, row)
            mincol, maxcol = min(mincol, col), max(maxcol, col)
            for rr in range(max(0, row - 1), min(height, row + 2)):
                for cc in range(max(0, col - 1), min(width, col + 2)):
                    i = rr * width + cc
                    if active[i] and not seen[i]:
                        seen[i] = 1
                        queue.append(i)
        components.append({
            "pixels": count,
            "bbox_pixels": [mincol, minrow, maxcol + 1, maxrow + 1],
            "mean_model_score": round(sum_score / count, 4),
            "peak_model_score": round(peak, 4),
        })
    components.sort(key=lambda item: item["pixels"], reverse=True)
    reviewed = [c for c in components if c["pixels"] >= MIN_REVIEW_COMPONENT_PIXELS]
    largest = reviewed[0]["pixels"] if reviewed else 0
    valid_count = sum(valid)
    count = sum(active)
    if valid_count == 0:
        tier = "unavailable"
        reason = "No pixels with a complete set of 14 input bands"
    elif count == 0:
        tier = "none_detected"
        reason = "No predicted scar pixels above the model threshold"
    elif largest >= HIGH_COMPONENT_PIXELS:
        tier = "high"
        reason = "At least one connected candidate covers 128 or more pixels"
    elif largest >= MEDIUM_COMPONENT_PIXELS:
        tier = "medium"
        reason = "At least one connected candidate covers 24 to 127 pixels"
    else:
        tier = "low"
        reason = "Only small or isolated candidate regions were predicted"
    return {
        "review_priority": tier,
        "reason": reason,
        "candidate_pixels": count,
        "valid_pixels": valid_count,
        "valid_fraction": round(valid_count / (width * height), 5),
        "connected_regions": len(components),
        "reviewable_regions": len(reviewed),
        "largest_reviewable_region_pixels": largest,
        "regions": reviewed[:12],
        "screening_method": "8-connected component pixel counts (heuristic, unvalidated)",
        "component_thresholds_pixels": {
            "min_review": MIN_REVIEW_COMPONENT_PIXELS,
            "medium": MEDIUM_COMPONENT_PIXELS,
            "high": HIGH_COMPONENT_PIXELS
        },
        "danger_assessment": "not_available",
        "hazard_probability_calibrated": False,
        "warning": (
            "This is post-event scar REVIEW PRIORITY, not danger, future "
            "landslide probability, or safety. Risk needs slope stability, "
            "fresh rainfall, runout, population, road/building exposure, "
            "and independent local validation."
        ),
    }
