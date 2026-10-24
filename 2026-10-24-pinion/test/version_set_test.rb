# frozen_string_literal: true

require_relative "test_helper"

class VersionSetTest < Minitest::Test
  include Helpers

  POINTS = begin
    pts = []
    (0..3).each { |a| (0..2).each { |b| (0..1).each { |p| pts << Version.new(a, b, p) } } }
    pts << Version.new(1, 0, 0, ["rc", "1"]) << Version.new(2, 0, 0, ["0"]) << Version.new(1, 1, 0, ["beta"])
    pts.uniq.sort
  end

  def random_set(rng)
    s = VersionSet.empty
    rng.rand(4).times do
      a = POINTS[rng.rand(POINTS.size)]
      b = POINTS[rng.rand(POINTS.size)]
      a, b = b, a if b < a
      s = s.union([VersionSet.between(a, b), VersionSet.gt(a).intersect(VersionSet.lte(b)), VersionSet.exact(a),
                   VersionSet.gte(a), VersionSet.lt(b), VersionSet.gt(a), VersionSet.lte(b)][rng.rand(7)])
    end
    rng.rand(4).zero? ? s.complement : s
  end

  def test_algebra_matches_pointwise_membership
    rng = Random.new(2024)
    1500.times do
      a = random_set(rng)
      b = random_set(rng)
      POINTS.each do |x|
        assert_equal a.include?(x) && b.include?(x), a.intersect(b).include?(x)
        assert_equal a.include?(x) || b.include?(x), a.union(b).include?(x)
        assert_equal !a.include?(x), a.complement.include?(x)
        assert_equal a.include?(x) && !b.include?(x), a.subtract(b).include?(x)
      end
    end
  end

  def test_algebraic_laws
    rng = Random.new(99)
    500.times do
      a = random_set(rng)
      b = random_set(rng)
      assert_equal a, a.complement.complement
      assert_equal a.union(b), b.union(a)
      assert_equal a.intersect(b), b.intersect(a)
      assert_equal a.union(b).complement, a.complement.intersect(b.complement) # De Morgan
      assert_equal VersionSet.any, a.union(a.complement)
      assert a.intersect(a.complement).empty?
      assert a.intersect(b).subset?(a)
      assert a.subset?(a.union(b))
      assert_equal a.subset?(b), a.subtract(b).empty?
      assert_equal a, a.union(a.intersect(b)) # absorption
    end
  end

  def test_canonical_form_makes_equal_sets_equal
    a = VersionSet.gte(v("1.0.0")).intersect(VersionSet.lt(v("2.0.0")))
    b = VersionSet.between(v("1.0.0"), v("1.5.0")).union(VersionSet.between(v("1.5.0"), v("2.0.0")))
    assert_equal a, b
    assert_equal 1, b.intervals.length
    assert_equal a.hash, b.hash
  end

  def test_adjacent_and_touching_boundaries
    assert_equal VersionSet.any, VersionSet.lte(v("1.0.0")).union(VersionSet.gt(v("1.0.0")))
    assert_equal VersionSet.any, VersionSet.lt(v("1.0.0")).union(VersionSet.gte(v("1.0.0")))
    refute_equal VersionSet.any, VersionSet.lt(v("1.0.0")).union(VersionSet.gt(v("1.0.0"))) # the point 1.0.0 is missing
    assert VersionSet.lt(v("1.0.0")).intersect(VersionSet.gt(v("1.0.0"))).empty?
    assert VersionSet.lte(v("1.0.0")).intersect(VersionSet.gte(v("1.0.0"))).singleton == v("1.0.0")
  end

  def test_singleton
    assert_equal v("1.2.3"), VersionSet.exact(v("1.2.3")).singleton
    assert_nil VersionSet.between(v("1.0.0"), v("2.0.0")).singleton
    assert_nil VersionSet.empty.singleton
  end

  def test_mentions_prerelease
    assert c(">=1.0.0-rc.1").mentions_prerelease?
    refute c("^1.2.3").mentions_prerelease? # the hidden 2.0.0-0 bound does not count
    refute c("*").mentions_prerelease?
  end

  def test_from_versions
    s = VersionSet.from_versions([v("1.0.0"), v("1.0.1"), v("3.0.0")])
    assert s.include?(v("1.0.1"))
    refute s.include?(v("2.0.0"))
    assert_equal 3, s.intervals.length
  end
end
