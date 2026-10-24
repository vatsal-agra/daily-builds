# frozen_string_literal: true

require_relative "test_helper"

class OracleTest < Minitest::Test
  include Helpers

  def universe(reg, **o) = Universe.new(registry(reg), **o)

  def test_oracle_finds_known_solution_and_proves_known_conflict
    reg = { "a" => { "1.0.0" => { "b" => "^1" }, "2.0.0" => { "b" => "^2" } }, "b" => { "1.0.0" => {}, "2.0.0" => {} } }
    u = universe(reg)
    assert_equal({ "a" => v("2.0.0"), "b" => v("2.0.0") }, Oracle.solve(u, { "a" => c("*") }))
    assert_nil Oracle.solve(u, { "a" => c("^2"), "b" => c("^1") })
  end

  def test_oracle_forced_terms
    reg = { "a" => { "1.0.0" => {}, "2.0.0" => {} } }
    u = universe(reg)
    assert_equal({ "a" => v("1.0.0") }, Oracle.solve(u, {}, forced: [Term.pos("a", c("^1"))]))
    assert_nil Oracle.solve(u, { "a" => c("^2") }, forced: [Term.pos("a", c("^1"))])
    assert_equal({}, Oracle.solve(u, {}, forced: [Term.neg("a", c("*"))]))
    assert_nil Oracle.solve(u, {}, forced: [Term.neg(Incompatibility::ROOT, VersionSet.any)])
  end

  def test_valid_catches_every_kind_of_bad_solution
    reg = { "a" => { "1.0.0" => { "b" => "^1" } }, "b" => { "1.0.0" => {}, "2.0.0" => {} }, "z" => { "1.0.0" => {} } }
    u = universe(reg)
    root = { "a" => c("*") }
    assert_empty Oracle.valid?(u, root, { "a" => v("1.0.0"), "b" => v("1.0.0") })
    assert Oracle.valid?(u, root, { "a" => v("1.0.0") }).any?                                   # missing dependency
    assert Oracle.valid?(u, root, { "a" => v("1.0.0"), "b" => v("2.0.0") }).any?                # violated constraint
    assert Oracle.valid?(u, root, { "a" => v("1.0.0"), "b" => v("1.0.0"), "z" => v("1.0.0") }).any? # unreachable extra
    assert Oracle.valid?(u, root, { "a" => v("9.9.9"), "b" => v("1.0.0") }).any?                # nonexistent version
    assert Oracle.valid?(u, root, {}).any?                                                       # root unmet
  end
end

class FuzzTest < Minitest::Test
  include Helpers

  def assert_clean(summary)
    assert_empty summary.failures.map { |f| [f.seed, f.problems.first(2)] }, "solver disagreed with the oracle"
    assert_equal summary.total, summary.sat + summary.unsat
  end

  def test_default_shape
    s = Fuzz.run(start: 1, count: 120)
    assert_clean s
    assert_operator s.sat, :>, 20      # the generator exercises both outcomes
    assert_operator s.unsat, :>, 20
    assert_operator s.clauses_checked, :>, 100
  end

  def test_denser_and_larger_shapes
    assert_clean Fuzz.run(start: 700, count: 50, gen: { packages: 8, versions: 6, density: 0.3 })
    assert_clean Fuzz.run(start: 800, count: 40, gen: { packages: 4, versions: 8, density: 0.6 })
    assert_clean Fuzz.run(start: 900, count: 40, gen: { packages: 3, versions: 3, density: 0.9, extras: false })
  end

  def test_generator_is_deterministic_and_valid
    a = Gen.generate(5)
    assert_equal a, Gen.generate(5)
    refute_equal a, Gen.generate(6)
    reg, man = a
    Registry.from_hash(reg)
    Manifest.from_hash(man)
  end

  # ---- the fuzzer itself must be able to fail: plant bugs and demand they are caught ----------

  # Replace klass#meth with the block (run with self = the receiver, original bound as first arg),
  # fuzz, then restore the original.
  def with_mutation(klass, meth, &mutant)
    orig = klass.instance_method(meth)
    klass.send(:define_method, meth) { |*a, &b| instance_exec(orig.bind(self), *a, &mutant) }
    old = Fuzz.solve_timeout
    Fuzz.solve_timeout = 0.5
    Fuzz.run(start: 1, count: 80, stop_after: 1)
  ensure
    Fuzz.solve_timeout = old
    klass.send(:define_method, meth, orig)
  end

  def test_fuzzer_catches_a_solver_that_ignores_term_constraints
    s = with_mutation(Solver, :candidates_for) { |orig, term| term.package == Incompatibility::ROOT ? orig.call(term) : @universe.versions(term.package) }
    refute_empty s.failures
  end

  def test_fuzzer_catches_a_solver_that_treats_overlap_as_satisfied
    s = with_mutation(Term, :relation) { |orig, known| (r = orig.call(known)) == :inconclusive ? :satisfied : r }
    refute_empty s.failures
  end

  def test_fuzzer_catches_unsound_range_widening
    s = with_mutation(Solver, :dep_incompat) do |orig, pkg, version, name, set, vs, lo = 0, hi = 0|
      orig.call(pkg, version, name, set, vs, 0, [vs.length - 1, 0].max) # always widen to every version
    end
    refute_empty s.failures
  end

  def test_fuzzer_catches_a_proof_with_lying_leaves
    s = with_mutation(Solver, :dep_incompat) do |orig, pkg, version, name, set, vs, lo = 0, hi = 0|
      inc = orig.call(pkg, version, name, set, vs, lo, hi)
      inc.cause.dep_set = VersionSet.any if inc.cause.is_a?(DependencyCause) && pkg != Incompatibility::ROOT && version.minor.odd?
      inc
    end
    refute_empty s.failures
  end
end
