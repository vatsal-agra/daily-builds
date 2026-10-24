# frozen_string_literal: true

require_relative "test_helper"

class VersionTest < Minitest::Test
  include Helpers

  def test_parse_and_to_s_round_trip
    %w[0.0.0 1.2.3 10.20.30 1.0.0-alpha 1.0.0-alpha.1 1.0.0-0.3.7 1.0.0-x.7.z.92 1.0.0+build.5 1.0.0-rc.1+b.7].each do |s|
      assert_equal s, v(s).to_s
    end
  end

  def test_rejects_malformed
    ["1", "1.2", "1.2.3.4", "01.2.3", "1.02.3", "1.2.3-", "1.2.3-01", "1.2.3-a..b", "1.2.3+", "v1.2.3", "", "a.b.c", "1.2.3-é"].each do |s|
      assert_raises(ParseError, s.inspect) { v(s) }
    end
  end

  def test_spec_precedence_chain
    chain = %w[1.0.0-alpha 1.0.0-alpha.1 1.0.0-alpha.beta 1.0.0-beta 1.0.0-beta.2 1.0.0-beta.11 1.0.0-rc.1 1.0.0 2.0.0 2.1.0 2.1.1].map { |s| v(s) }
    chain.each_cons(2) { |a, b| assert_operator a, :<, b, "#{a} < #{b}" }
    assert_equal chain, chain.shuffle(random: Random.new(3)).sort
  end

  def test_numeric_identifiers_compare_numerically_and_sort_below_alphanumeric
    assert_operator v("1.0.0-2"), :<, v("1.0.0-10")
    assert_operator v("1.0.0-9"), :<, v("1.0.0-a")
  end

  def test_build_metadata_is_ignored_for_equality_and_order
    assert_equal v("1.0.0+a"), v("1.0.0+b")
    assert_equal 0, v("1.0.0+a") <=> v("1.0.0+z")
    assert_equal v("1.0.0+a").hash, v("1.0.0+b").hash
  end

  def test_next_helpers_use_lowest_prerelease
    assert_equal "2.0.0-0", v("1.4.7").next_major.to_s
    assert_equal "1.5.0-0", v("1.4.7").next_minor.to_s
    assert_operator v("2.0.0-0"), :<, v("2.0.0-alpha")
    assert_operator v("2.0.0-0"), :>, v("1.9.9")
  end

  def test_prerelease_predicate
    assert v("1.0.0-a").prerelease?
    refute v("1.0.0").prerelease?
    refute v("1.0.0+b").prerelease?
  end
end
