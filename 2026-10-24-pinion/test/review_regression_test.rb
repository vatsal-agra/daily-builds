# frozen_string_literal: true

require_relative "test_helper"

# One regression test per finding in REVIEW.md.
class ReviewRegressionTest < Minitest::Test
  include Helpers

  def test_f1_empty_alternatives_are_errors_not_nil
    ["||", "^1 ||", "|| ^1", "^1 || || ^2"].each do |s|
      assert_raises(ParseError, s) { Constraint.parse(s) }
    end
  end

  def test_f2_operator_without_version_has_clear_message
    e = assert_raises(ParseError) { Constraint.parse("~>") }
    assert_match(/needs a version/, e.message)
    e = assert_raises(ParseError) { Constraint.parse("1.2.3 - ") }
    assert_match(/dangling/, e.message)
  end

  def test_f3_display_never_leaks_internal_minus_zero_bound
    assert_equal "<1.2.0 || >=1.3.0", c("!=1.2").to_s
    refute_match(/-0/, c("^1.2.3").complement.to_s)
  end

  def test_f4_zero_zero_range_is_not_shown_as_a_caret
    s = VersionSet.between(v("0.0.0"), Version.new(0, 1, 0, ["0"]))
    assert_equal ">=0.0.0 <0.1.0", s.to_s
    assert_equal "^0.2.3", c("^0.2.3").to_s
    assert_equal ">=0.0.3 <0.0.4", c("^0.0.3").to_s
  end

  def test_f5_stable_beats_a_numerically_higher_prerelease
    reg = { "lib" => { "1.9.0" => {}, "2.0.0-rc.1" => {} } }
    man = manifest({ "lib" => "*" }, allow_prerelease: ["lib"])
    assert_equal "1.9.0", solve(reg, man).fetch("lib")
    assert_equal "2.0.0-rc.1", solve(reg, manifest({ "lib" => ">=2.0.0-rc.1" })).fetch("lib")
  end

  def test_f6_reporter_survives_very_deep_proofs
    n = 2500
    pk = (0...n).to_h { |i| ["c#{i}", { "1.0.0" => { "c#{i + 1}" => "^1" } }] }
    pk["c#{n}"] = { "2.0.0" => {} }
    text = explain(pk, { "c0" => "^1" })
    assert_operator text.lines.length, :>, n
    assert_includes text, "version solving failed"
  end

  def test_f7_self_dependency_is_handled
    # 1.2.0 depends on itself (vacuous); 1.1.0 depends on itself with a range excluding itself
    reg = { "p" => { "1.1.0" => { "p" => "^1.2.0" }, "1.2.0" => { "p" => "^1.2.0" } } }
    assert_equal({ "p" => "1.2.0" }, solve(reg, { "p" => "*" }))
    assert_equal({ "p" => "1.2.0" }, solve(reg, { "p" => "*" }, strategy: :oldest))
  end

  def test_f8_cli_internal_errors_use_exit_code_70_and_no_trace
    out = IO.popen([RbConfig.ruby, File.expand_path("../bin/pinion", __dir__), "range", "||"], err: [:child, :out], &:read)
    assert_match(/error: empty alternative/, out)
    refute_match(/\.rb:\d+/, out)
  end

  def test_f9_why_unknown_package_says_so
    with_project({ "packages" => { "a" => { "1.0.0" => {} }, "b" => { "1.0.0" => {} } } }, { "name" => "x", "dependencies" => { "a" => "*" } }) do |dir|
      code, out, = cli("why", "b", cwd: dir)
      assert_equal 1, code
      assert_match(/exists in the registry/, out)
      _, out, = cli("why", "zzz", cwd: dir)
      assert_match(/does not exist in the registry/, out)
    end
  end
end

class ReviewRegressionLockTest < Minitest::Test
  include Helpers

  def test_f12_verify_warns_about_yanked_locked_versions
    reg = { "packages" => { "a" => { "1.0.0" => {} } } }
    with_project(reg, { "name" => "x", "dependencies" => { "a" => "*" } }) do |dir|
      assert_equal 0, cli("lock", cwd: dir)[0]
      reg["packages"]["a"]["1.0.0"]["yanked"] = true
      File.write(File.join(dir, "registry.json"), JSON.generate(reg))
      code, out, = cli("verify", cwd: dir)
      assert_equal 0, code
      assert_match(/warning: a 1.0.0 has been yanked/, out)
    end
  end
end
