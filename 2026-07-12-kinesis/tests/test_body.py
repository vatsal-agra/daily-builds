import random
import unittest

from kinesis import vecmath as vm
from kinesis.genome import Genome
from kinesis.body import build_phenotype, GROUND_CLEARANCE


class TestPhenotypeConstruction(unittest.TestCase):
    def test_joint_anchors_coincide_at_rest_pose(self):
        rng = random.Random(0)
        for _ in range(15):
            g = Genome.random(rng)
            phenotype = build_phenotype(g)
            for joint in phenotype.joints:
                world_a = joint.a.local_to_world(joint.anchor_a)
                world_b = joint.b.local_to_world(joint.anchor_b)
                dist = vm.length(vm.sub(world_a, world_b))
                self.assertLess(dist, 1e-9,
                                 "joint anchors must exactly coincide at construction "
                                 "so the solver starts from zero constraint error")

    def test_lowest_corner_sits_at_ground_clearance(self):
        rng = random.Random(1)
        for _ in range(15):
            g = Genome.random(rng)
            phenotype = build_phenotype(g)
            min_y = min(c[1] for b in phenotype.bodies for c in b.corners())
            self.assertAlmostEqual(min_y, GROUND_CLEARANCE, places=9)

    def test_single_node_genome_has_no_joints(self):
        from kinesis.genome import GenomeNode
        g = Genome(GenomeNode(0.5, 0.3), 1.0)
        phenotype = build_phenotype(g)
        self.assertEqual(len(phenotype.bodies), 1)
        self.assertEqual(len(phenotype.joints), 0)
        self.assertEqual(len(phenotype.bindings), 0)

    def test_mirror_produces_second_body_on_opposite_side(self):
        from kinesis.genome import GenomeNode, CPG
        root = GenomeNode(1.0, 0.3)
        limb = GenomeNode(0.4, 0.15, attach_t=0.0, attach_side=1.0, rest_angle=0.3,
                           limit_span=1.0, mirror=True, cpg=CPG(0.5, 1.0, 0.0, 0.0))
        root.children.append(limb)
        g = Genome(root, 1.0)
        phenotype = build_phenotype(g)
        # root + 2 limb copies (original + mirror)
        self.assertEqual(len(phenotype.bodies), 3)
        self.assertEqual(len(phenotype.joints), 2)
        j1, j2 = phenotype.joints
        # mirrored copy attaches on the opposite face (attach_side flips sign)
        self.assertAlmostEqual(j1.anchor_a[1], -j2.anchor_a[1], places=9)
        # and its rest angle is the negation of the original's
        self.assertAlmostEqual(j1.rest_angle, -j2.rest_angle, places=9)
        # phase shift: original binding has no shift, mirrored has +pi
        shifts = sorted(b.phase_shift for b in phenotype.bindings)
        self.assertAlmostEqual(shifts[0], 0.0, places=9)
        self.assertAlmostEqual(shifts[1], 3.141592653589793, places=9)


if __name__ == "__main__":
    unittest.main()
