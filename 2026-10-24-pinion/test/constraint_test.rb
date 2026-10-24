# frozen_string_literal: true

require_relative "test_helper"

class ConstraintTest < Minitest::Test
  include Helpers

  # constraint => [matching versions, non-matching versions]
  TABLE = {
    "1.2.3" => [%w[1.2.3], %w[1.2.4 1.2.2 1.2.3-rc.1]],
    "=1.2.3" => [%w[1.2.3], %w[1.2.4]],
    "==1.2.3" => [%w[1.2.3], %w[1.3.0]],
    "*" => [%w[0.0.1 99.0.0], []],
    "" => [%w[1.0.0], []],
    "1" => [%w[1.0.0 1.9.9], %w[0.9.9 2.0.0]],
    "1.x" => [%w[1.0.0 1.9.9], %w[2.0.0]],
    "1.2" => [%w[1.2.0 1.2.9], %w[1.3.0 1.1.9]],
    "1.2.x" => [%w[1.2.0 1.2.9], %w[1.3.0]],
    "^1.2.3" => [%w[1.2.3 1.9.0], %w[1.2.2 2.0.0 2.0.0-alpha]],
    "^0.2.3" => [%w[0.2.3 0.2.9], %w[0.3.0 0.2.2]],
    "^0.0.3" => [%w[0.0.3], %w[0.0.4 0.0.2]],
    "^0.0" => [%w[0.0.0 0.0.9], %w[0.1.0]],
    "^0" => [%w[0.0.0 0.9.9], %w[1.0.0]],
    "^1.2.3-beta.2" => [%w[1.2.3-beta.2 1.2.3-beta.11 1.2.3 1.5.0], %w[1.2.3-beta.1 2.0.0]],
    "~1.2.3" => [%w[1.2.3 1.2.9], %w[1.3.0 1.2.2]],
    "~1.2" => [%w[1.2.0 1.2.9], %w[1.3.0]],
    "~1" => [%w[1.0.0 1.9.9], %w[2.0.0]],
    "~>1.2" => [%w[1.2.0 1.9.0], %w[2.0.0 1.1.9]],
    "~> 1.2.3" => [%w[1.2.3 1.2.9], %w[1.3.0]],
    "~> 0.0.3" => [%w[0.0.3 0.0.9], %w[0.1.0]],
    ">=1.0.0" => [%w[1.0.0 5.0.0], %w[0.9.9]],
    ">1.0.0" => [%w[1.0.1 2.0.0], %w[1.0.0 0.5.0]],
    "<2.0.0" => [%w[1.9.9 0.0.1], %w[2.0.0 3.0.0]],
    "<=2.0.0" => [%w[2.0.0 1.0.0], %w[2.0.1]],
    ">1.2" => [%w[1.3.0 2.0.0], %w[1.2.9 1.2.0]],
    "<=1.2" => [%w[1.2.9 1.0.0], %w[1.3.0]],
    "!=1.5.0" => [%w[1.4.9 1.5.1], %w[1.5.0]],
    "!=1.5" => [%w[1.4.9 1.6.0], %w[1.5.0 1.5.7]],
    ">=1.0.0 <2.0.0" => [%w[1.0.0 1.99.0], %w[0.9.0 2.0.0]],
    ">=1.0.0, <2.0.0" => [%w[1.5.0], %w[2.0.0]],
    ">= 1.0.0, < 2.0.0" => [%w[1.5.0], %w[2.0.0]],
    ">=1.0 <1.0" => [[], %w[1.0.0 0.9.0 1.0.1]],
    "^1.0.0 || ^3.0.0" => [%w[1.5.0 3.2.0], %w[2.0.0 4.0.0]],
    "<1.0.0 || >=2.0.0" => [%w[0.5.0 2.0.0], %w[1.0.0 1.5.0]],
    "1.0.0 - 2.0.0" => [%w[1.0.0 1.5.0 2.0.0], %w[2.0.1 0.9.9]],
    "1.2.3 - 2.3" => [%w[1.2.3 2.3.9], %w[2.4.0]],
    ">=1.0.0-rc.1" => [%w[1.0.0-rc.1 1.0.0-rc.2 1.0.0], %w[1.0.0-beta]],
    "  ^1  ||\t^3 " => [%w[1.0.0 3.0.0], %w[2.0.0]],
  }.freeze

  TABLE.each do |src, (yes, no)|
    define_method("test_#{src.hash.abs}_#{src.gsub(/\W+/, '_')}") do
      set = c(src)
      yes.each { |s| assert set.include?(v(s)), "#{src.inspect} should match #{s} (set: #{set})" }
      no.each { |s| refute set.include?(v(s)), "#{src.inspect} should not match #{s} (set: #{set})" }
    end
  end

  def test_errors
    ["^", "~>", ">=", "||", "^1 ||", "|| ^1", "1.*.3", "latest", "^^2", "1.2.3 - ", ">>1", "1.2.3-", "^1.x.3", "1.x-beta"].each do |s|
      assert_raises(ParseError, s.inspect) { c(s) }
    end
  end

  def test_normal_forms_are_readable
    assert_equal "^1.2.3", c("^1.2.3").to_s
    assert_equal "~1.2.3", c("~1.2.3").to_s
    assert_equal "1.2.3", c("=1.2.3").to_s
    assert_equal ">=1.0.0 <2.0.0", c(">=1.0.0, <2").to_s
    assert_equal "any", c("*").to_s
    assert_equal "none", c(">=2 <1").to_s
    assert_equal "^1.0.0 || ^3.0.0", c("^1 || ^3").to_s
  end

  def test_display_reparses_to_the_same_release_membership
    samples = (0..4).flat_map { |a| (0..3).flat_map { |b| (0..2).map { |p| Version.new(a, b, p) } } }
    TABLE.each_key do |src|
      set = c(src)
      next if set.empty? || set.any?
      again = c(set.to_s)
      samples.each { |x| assert_equal set.include?(x), again.include?(x), "#{src} -> #{set} differs at #{x}" }
    end
  end
end
