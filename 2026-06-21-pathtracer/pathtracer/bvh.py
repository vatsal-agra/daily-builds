"""BVH acceleration structure with Surface Area Heuristic (SAH) splitting."""
import math

from .shapes import AABB, HittableList


_SAH_BINS = 12        # candidate split positions per axis
_TRAVERSAL_COST = 1.0  # relative cost of traversing a node vs intersecting a primitive
_LEAF_MAX = 4         # max primitives in a leaf node


class BVHNode:
    """Recursive BVH node with SAH-optimal splitting."""

    def __init__(self, objects):
        """Build BVH from a list of hittable objects."""
        n = len(objects)

        if n == 1:
            self.left = objects[0]
            self.right = objects[0]
        elif n == 2:
            self.left = objects[0]
            self.right = objects[1]
        else:
            # Find best split using SAH
            axis, pos = _sah_split(objects)
            objects.sort(key=lambda o: _centroid_axis(o, axis))
            mid = _partition_at(objects, axis, pos)
            if mid == 0 or mid == n:
                mid = n // 2  # fallback: median split

            left_objs = objects[:mid]
            right_objs = objects[mid:]

            self.left = (left_objs[0] if len(left_objs) == 1
                         else BVHNode(left_objs))
            self.right = (right_objs[0] if len(right_objs) == 1
                          else BVHNode(right_objs))

        self.bbox = AABB.surrounding(
            self.left.bounding_box(),
            self.right.bounding_box(),
        )

    def hit(self, ray, t_min, t_max):
        if not self.bbox.hit(ray, t_min, t_max):
            return None
        hit_left = self.left.hit(ray, t_min, t_max)
        t_right_max = hit_left.t if hit_left is not None else t_max
        hit_right = self.right.hit(ray, t_min, t_right_max)
        return hit_right if hit_right is not None else hit_left

    def bounding_box(self):
        return self.bbox


# ---------- SAH helpers ----------

def _centroid_axis(obj, axis):
    bb = obj.bounding_box()
    c = (bb.mn, bb.mx)
    lo = (bb.mn.x, bb.mn.y, bb.mn.z)[axis]
    hi = (bb.mx.x, bb.mx.y, bb.mx.z)[axis]
    return (lo + hi) * 0.5


def _sah_split(objects):
    """Return (best_axis, best_split_pos) using binned SAH."""
    # Compute overall centroid bounds
    all_boxes = [o.bounding_box() for o in objects]
    total_area = _union_boxes(all_boxes).surface_area()
    if total_area < 1e-12:
        return 0, 0.0

    best_cost = math.inf
    best_axis = 0
    best_pos = 0.0

    for axis in range(3):
        centroids = [_centroid_axis(o, axis) for o in objects]
        c_min = min(centroids)
        c_max = max(centroids)
        if c_max - c_min < 1e-12:
            continue

        for bi in range(1, _SAH_BINS):
            split = c_min + (c_max - c_min) * bi / _SAH_BINS
            left_boxes = [b for b, c in zip(all_boxes, centroids) if c < split]
            right_boxes = [b for b, c in zip(all_boxes, centroids) if c >= split]
            if not left_boxes or not right_boxes:
                continue
            l_area = _union_boxes(left_boxes).surface_area()
            r_area = _union_boxes(right_boxes).surface_area()
            cost = (_TRAVERSAL_COST +
                    (l_area * len(left_boxes) + r_area * len(right_boxes)) / total_area)
            if cost < best_cost:
                best_cost = cost
                best_axis = axis
                best_pos = split

    return best_axis, best_pos


def _union_boxes(boxes):
    box = boxes[0]
    for b in boxes[1:]:
        box = AABB.surrounding(box, b)
    return box


def _partition_at(objects, axis, pos):
    """Return index i such that objects[:i] have centroid < pos on axis."""
    return sum(1 for o in objects if _centroid_axis(o, axis) < pos)


def build_bvh(objects):
    """Build a BVHNode from a list of objects (or return HittableList for ≤1)."""
    if not objects:
        return HittableList()
    if len(objects) == 1:
        return objects[0]
    return BVHNode(list(objects))
