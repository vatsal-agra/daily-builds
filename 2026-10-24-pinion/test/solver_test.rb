# frozen_string_literal: true

require_relative "test_helper"

class SolverTest < Minitest::Test
  include Helpers

  def test_single_package_picks_newest
    assert_equal({ "a" => "1.2.0" }, solve({ "a" => { "1.0.0" => {}, "1.1.0" => {}, "1.2.0" => {} } }, { "a" => "*" }))
  end

  def test_oldest_strategy
    reg = { "a" => { "1.0.0" => {}, "1.1.0" => {}, "2.0.0" => {} } }
    assert_equal({ "a" => "1.0.0" }, solve(reg, { "a" => "*" }, strategy: :oldest))
    assert_equal({ "a" => "1.1.0" }, solve(reg, { "a" => "^1" }, strategy: :newest))
  end

  def test_unknown_strategy_is_rejected
    assert_raises(ArgumentError) { solve({ "a" => { "1.0.0" => {} } }, { "a" => "*" }, strategy: :random) }
  end

  def test_transitive_dependencies_are_included
    reg = { "a" => { "1.0.0" => { "b" => "^1" } }, "b" => { "1.0.0" => { "c" => "^1" }, "1.1.0" => { "c" => "^1" } }, "c" => { "1.0.0" => {}, "2.0.0" => {} } }
    assert_equal({ "a" => "1.0.0", "b" => "1.1.0", "c" => "1.0.0" }, solve(reg, { "a" => "*" }))
  end

  def test_diamond_picks_a_version_satisfying_both_sides
    reg = {
      "app-a" => { "1.0.0" => { "shared" => ">=1.0.0 <3.0.0" } },
      "app-b" => { "1.0.0" => { "shared" => ">=2.0.0" } },
      "shared" => { "1.0.0" => {}, "2.0.0" => {}, "2.5.0" => {}, "3.0.0" => {} }
    }
    assert_equal "2.5.0", solve(reg, { "app-a" => "*", "app-b" => "*" })["shared"]
  end

  def test_backtracks_to_older_version_when_newest_conflicts
    reg = {
      "a" => { "1.0.0" => { "c" => "^1" }, "2.0.0" => { "c" => "^2" } },
      "b" => { "1.0.0" => { "c" => "^1" } },
      "c" => { "1.0.0" => {}, "1.5.0" => {}, "2.0.0" => {} }
    }
    assert_equal({ "a" => "1.0.0", "b" => "1.0.0", "c" => "1.5.0" }, solve(reg, { "a" => "*", "b" => "*" }))
  end

  def test_deep_backtracking_needs_learning
    # a2 -> b2 -> c2 -> d2 dead-ends on d; only the all-1 chain works.
    reg = {}
    %w[a b c].zip(%w[b c d]).each do |p, n|
      reg[p] = { "1.0.0" => { n => "^1" }, "2.0.0" => { n => "^2" } }
    end
    reg["d"] = { "1.0.0" => {}, "2.0.0" => { "zzz" => "^9" } }
    assert_equal({ "a" => "1.0.0", "b" => "1.0.0", "c" => "1.0.0", "d" => "1.0.0" }, solve(reg, { "a" => "*" }))
  end

  def test_mutual_dependency_cycle
    reg = { "a" => { "1.0.0" => { "b" => "^1" } }, "b" => { "1.0.0" => { "a" => "^1" } } }
    assert_equal({ "a" => "1.0.0", "b" => "1.0.0" }, solve(reg, { "a" => "*" }))
  end

  def test_cycle_with_version_interlock
    reg = {
      "a" => { "1.0.0" => { "b" => "^1" }, "2.0.0" => { "b" => "^2" } },
      "b" => { "1.0.0" => { "a" => "^1" }, "2.0.0" => { "a" => "^2" } }
    }
    assert_equal({ "a" => "2.0.0", "b" => "2.0.0" }, solve(reg, { "a" => "*" }))
    assert_equal({ "a" => "1.0.0", "b" => "1.0.0" }, solve(reg, { "b" => "^1" }))
  end

  def test_self_dependency_is_harmless
    reg = { "a" => { "1.0.0" => { "a" => "^1" } } }
    assert_equal({ "a" => "1.0.0" }, solve(reg, { "a" => "*" }))
  end

  def test_unreachable_packages_are_not_selected
    reg = { "a" => { "1.0.0" => {} }, "unused" => { "1.0.0" => {} } }
    assert_equal({ "a" => "1.0.0" }, solve(reg, { "a" => "*" }))
  end

  def test_empty_manifest
    assert_equal({}, solve({ "a" => { "1.0.0" => {} } }, {}))
  end

  # ---- locks -------------------------------------------------------------------

  def test_locked_version_is_preferred_when_allowed
    reg = { "a" => { "1.0.0" => {}, "1.1.0" => {}, "1.2.0" => {} } }
    assert_equal "1.1.0", solve(reg, { "a" => "^1" }, locked: { "a" => v("1.1.0") })["a"]
  end

  def test_locked_version_is_ignored_when_constraints_forbid_it
    reg = { "a" => { "1.0.0" => {}, "2.0.0" => {} } }
    assert_equal "2.0.0", solve(reg, { "a" => "^2" }, locked: { "a" => v("1.0.0") })["a"]
  end

  def test_locked_version_that_no_longer_exists_is_ignored
    reg = { "a" => { "1.0.0" => {}, "1.1.0" => {} } }
    assert_equal "1.1.0", solve(reg, { "a" => "*" }, locked: { "a" => v("1.0.9") })["a"]
  end

  def test_full_lock_reproduces_the_solution_under_any_strategy
    reg = { "a" => { "1.0.0" => { "b" => "*" }, "1.1.0" => { "b" => "*" } }, "b" => { "1.0.0" => {}, "2.0.0" => {} } }
    first = solve(reg, { "a" => "*" })
    locked = first.transform_values { |s| v(s) }
    assert_equal first, solve(reg, { "a" => "*" }, strategy: :oldest, locked: locked)
  end

  # ---- yanked / prerelease policy ------------------------------------------------

  def test_yanked_versions_are_never_chosen_fresh
    reg = { "a" => { "1.0.0" => {}, "1.1.0" => { yanked: true } } }
    assert_equal "1.0.0", solve(reg, { "a" => "*" })["a"]
  end

  def test_yanked_version_is_kept_when_locked
    reg = { "a" => { "1.0.0" => {}, "1.1.0" => { yanked: true } } }
    assert_equal "1.1.0", solve(reg, { "a" => "*" }, locked: { "a" => v("1.1.0") })["a"]
  end

  def test_prereleases_hidden_by_default
    reg = { "a" => { "1.0.0" => {}, "2.0.0-beta.1" => {} } }
    assert_equal "1.0.0", solve(reg, { "a" => "*" })["a"]
    assert_match(/hidden|prerelease/, explain({ "a" => { "2.0.0-beta.1" => {} } }, { "a" => "*" }))
  end

  def test_prerelease_opt_in_via_manifest_list_flag_and_explicit_range
    reg = { "a" => { "1.0.0" => {}, "2.0.0-beta.1" => {}, "2.0.0-beta.2" => {} } }
    only_pre = { "a" => { "2.0.0-beta.1" => {}, "2.0.0-beta.2" => {} } }
    assert_equal "2.0.0-beta.2", solve(only_pre, manifest({ "a" => "*" }, allow_prerelease: ["a"]))["a"]
    assert_equal "2.0.0-beta.2", solve(only_pre, manifest({ "a" => "*" }, allow_prerelease: true))["a"]
    assert_equal "2.0.0-beta.2", solve(reg, { "a" => ">=2.0.0-beta.1" })["a"]
    assert_equal "1.0.0", solve(reg, manifest({ "a" => "*" }, allow_prerelease: ["a"]))["a"] # stable preferred
  end

  def test_dependency_ranges_do_not_pull_in_prereleases
    reg = { "a" => { "1.0.0" => { "b" => "^1.0.0" } }, "b" => { "1.0.0" => {}, "1.1.0-rc.1" => {} } }
    assert_equal "1.0.0", solve(reg, { "a" => "*" })["b"]
  end

  # ---- failures -------------------------------------------------------------------

  def test_unsolvable_raises_no_solution_with_incompatibility
    reg = { "a" => { "1.0.0" => {} } }
    e = assert_raises(NoSolution) { solve(reg, { "a" => "^2" }) }
    assert e.incompatibility.failure? || e.incompatibility.terms.any?
  end

  def test_solver_reports_stats
    reg = {}
    %w[a b c].zip(%w[b c d]).each { |p, n| reg[p] = { "1.0.0" => { n => "^1" }, "2.0.0" => { n => "^2" } } }
    reg["d"] = { "1.0.0" => {}, "2.0.0" => { "zzz" => "^9" } }
    res = Pinion.resolve(manifest({ "a" => "*" }), registry(reg))
    assert_operator res.stats[:decisions], :>=, 4
    assert_operator res.stats[:conflicts], :>=, 1
    assert_operator res.stats[:backjumps], :>=, 1
  end

  def test_conflict_driven_learning_happens_on_random_registries
    learned = 0
    (1..60).each do |seed|
      reg, man = Gen.generate(seed)
      solver = Solver.new(Universe.new(Registry.from_hash(reg)), Manifest.from_hash(man).dependencies)
      begin
        solver.solve
      rescue NoSolution
        nil
      end
      learned += solver.learned.length
      assert_equal solver.stats[:learned], solver.learned.length
    end
    assert_operator learned, :>, 10
  end

  def test_large_graph_resolves_quickly
    n = 400
    pk = (0...n).to_h { |i| ["c#{i}", { "1.0.0" => (i < n - 1 ? { "c#{i + 1}" => "^1" } : {}) }] }
    t = Process.clock_gettime(Process::CLOCK_MONOTONIC)
    assert_equal n, solve(pk, { "c0" => "^1" }).size
    assert_operator Process.clock_gettime(Process::CLOCK_MONOTONIC) - t, :<, 10
  end

  def test_many_versions_dependency_range_widening_keeps_work_small
    versions = (1..60).to_h { |i| ["1.#{i}.0", { "leaf" => "^1" }] }
    reg = { "mid" => versions, "leaf" => { "1.0.0" => {}, "2.0.0" => {} } }
    res = Pinion.resolve(manifest({ "mid" => "*", "leaf" => "^2" }), registry(reg)) rescue nil
    assert_nil res # leaf ^1 vs ^2 genuinely conflicts for every mid
    text = explain(reg, { "mid" => "*", "leaf" => "^2" })
    assert_includes text, "every version of mid depends on leaf ^1.0.0" # 60 versions summarised in one fact
  end
end
