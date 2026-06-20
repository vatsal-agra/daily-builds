"""Surface Area Heuristic (SAH) BVH builder + traversal."""
import math
from .aabb import AABB
from .materials import HitRecord


class BVHNode:
    """Internal BVH node with a left child, right child, and bounding box."""
    __slots__ = ('left', 'right', 'bbox')

    def __init__(self, left, right, bbox):
        self.left = left
        self.right = right
        self.bbox = bbox

    def hit(self, ray, t_min, t_max, rec):
        if not self.bbox.hit(ray, t_min, t_max):
            return False
        hit_left  = self.left.hit(ray, t_min, t_max, rec)
        hit_right = self.right.hit(ray, t_min, rec.t if hit_left else t_max, rec)
        return hit_left or hit_right

    def bounding_box(self):
        return self.bbox


def build_bvh(objects, depth=0):
    """Recursively build a BVH over a list of primitives using SAH splits."""
    n = len(objects)
    if n == 0:
        raise ValueError("Empty primitive list")
    if n == 1:
        return objects[0]
    if n == 2:
        bbox = AABB.surrounding(objects[0].bounding_box(), objects[1].bounding_box())
        return BVHNode(objects[0], objects[1], bbox)

    # Compute centroid AABB to find best split axis
    centroids = [_centroid(o.bounding_box()) for o in objects]
    cx = [c.x for c in centroids]
    cy = [c.y for c in centroids]
    cz = [c.z for c in centroids]
    spans = [max(cx) - min(cx), max(cy) - min(cy), max(cz) - min(cz)]
    axis = spans.index(max(spans))

    # SAH binned search on the chosen axis
    best_cost, best_idx, best_axis = float('inf'), n // 2, axis
    for ax in range(3):
        cost, idx = _sah_split(objects, ax)
        if cost < best_cost:
            best_cost = cost
            best_idx = idx
            best_axis = ax

    key = [lambda o: o.bounding_box().minimum.x + o.bounding_box().maximum.x,
           lambda o: o.bounding_box().minimum.y + o.bounding_box().maximum.y,
           lambda o: o.bounding_box().minimum.z + o.bounding_box().maximum.z][best_axis]
    objects = sorted(objects, key=key)

    left  = build_bvh(objects[:best_idx], depth + 1)
    right = build_bvh(objects[best_idx:], depth + 1)
    bbox  = AABB.surrounding(left.bounding_box(), right.bounding_box())
    return BVHNode(left, right, bbox)


def _centroid(bbox):
    return (bbox.minimum + bbox.maximum) * 0.5


def _sah_split(objects, axis):
    """Return (best_cost, best_split_index) for given axis using 8 bins."""
    n = len(objects)
    key = [lambda o: o.bounding_box().minimum.x + o.bounding_box().maximum.x,
           lambda o: o.bounding_box().minimum.y + o.bounding_box().maximum.y,
           lambda o: o.bounding_box().minimum.z + o.bounding_box().maximum.z][axis]
    sorted_objs = sorted(objects, key=key)

    # Prefix SA from left, suffix SA from right
    left_boxes = []
    box = None
    for obj in sorted_objs:
        b = obj.bounding_box()
        box = b if box is None else AABB.surrounding(box, b)
        left_boxes.append(box)

    right_boxes = []
    box = None
    for obj in reversed(sorted_objs):
        b = obj.bounding_box()
        box = b if box is None else AABB.surrounding(box, b)
        right_boxes.append(box)
    right_boxes.reverse()

    parent_area = left_boxes[-1].surface_area()
    if parent_area == 0:
        return float('inf'), n // 2

    best_cost = float('inf')
    best_idx = n // 2
    for i in range(1, n):
        la = left_boxes[i - 1].surface_area()
        ra = right_boxes[i].surface_area()
        cost = (la * i + ra * (n - i)) / parent_area
        if cost < best_cost:
            best_cost = cost
            best_idx = i

    return best_cost, best_idx
