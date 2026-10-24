# frozen_string_literal: true

require "timeout"
require_relative "resolver"
require_relative "oracle"
require_relative "gen"

module Pinion
  # Differential fuzzer: random registries, real solver vs. brute-force oracle, plus proof checks.
  module Fuzz
    Outcome = Struct.new(:seed, :sat, :problems, :stats)
    Summary = Struct.new(:total, :sat, :unsat, :failures, :stats, :clauses_checked)

    @solve_timeout = 5
    class << self
      attr_accessor :solve_timeout
    end

    module_function

    def run(start: 1, count: 200, gen: {}, stop_after: nil)
      sum = Summary.new(0, 0, 0, [], Hash.new(0), 0)
      count.times do |i|
        o = check(start + i, **gen)
        sum.total += 1
        o.sat ? sum.sat += 1 : sum.unsat += 1
        o.stats.each { |k, v| sum.stats[k] += v }
        sum.clauses_checked += o.stats[:clauses_checked].to_i
        sum.failures << o unless o.problems.empty?
        yield o if block_given?
        break if stop_after && sum.failures.length >= stop_after
      end
      sum
    end

    def check(seed, **gen)
      reg_h, man_h = Gen.generate(seed, **gen)
      registry = Registry.from_hash(reg_h)
      manifest = Manifest.from_hash(man_h)
      universe = Universe.new(registry, allow_prerelease: manifest.allow_prerelease)
      truth = Oracle.solve(universe, manifest.dependencies)
      problems = []
      stats = Hash.new(0)
      first_solution = nil

      %i[newest oldest].each do |strategy|
        solver = Solver.new(universe, manifest.dependencies, strategy: strategy)
        begin
          sol = Timeout.timeout(Fuzz.solve_timeout) { solver.solve }
          if truth.nil?
            problems << "#{strategy}: solver found #{sol} but the oracle proves unsatisfiable"
          else
            bad = Oracle.valid?(universe, manifest.dependencies, sol)
            problems.concat(bad.map { |b| "#{strategy}: invalid solution: #{b}" })
            first_solution ||= sol if strategy == :newest
          end
          check_clauses(universe, manifest, solver.learned, problems, stats, "#{strategy} learned clause")
        rescue Timeout::Error
          problems << "#{strategy}: solver did not finish within #{Fuzz.solve_timeout}s (non-termination?)"
        rescue NoSolution => e
          if truth
            problems << "#{strategy}: solver says unsatisfiable but oracle found #{truth}"
          else
            check_proof(universe, manifest, e.incompatibility, problems, stats, strategy)
          end
          check_clauses(universe, manifest, solver.learned, problems, stats, "#{strategy} learned clause")
        end
        solver.stats.each { |k, v| stats[k] += v }
      end

      if first_solution && problems.empty?
        # Locking everything must make any strategy reproduce exactly that solution.
        again = Solver.new(universe, manifest.dependencies, strategy: :oldest, locked: first_solution).solve
        problems << "lock round-trip differs: #{first_solution} vs #{again}" unless again == first_solution
      end
      Outcome.new(seed, !truth.nil?, problems, stats)
    end

    # Every derived incompatibility must be a *logical consequence* of the registry facts:
    # the oracle must find no valid world in which all of its terms hold.
    def check_clauses(universe, manifest, incs, problems, stats, label)
      incs.each do |inc|
        stats[:clauses_checked] += 1
        world = Oracle.solve(universe, manifest.dependencies, forced: inc.terms)
        problems << "#{label} is not entailed by the registry; counter-world #{world}" if world
      end
    end

    def check_proof(universe, manifest, failure, problems, stats, strategy)
      nodes = []
      seen = {}
      stack = [failure]
      until stack.empty?
        n = stack.pop
        next if seen[n.object_id]
        seen[n.object_id] = true
        nodes << n
        stack.push(n.cause.conflict, n.cause.other) if n.conflict?
      end
      derived = nodes.select(&:conflict?)
      leaves = nodes.reject(&:conflict?)
      check_clauses(universe, manifest, derived, problems, stats, "#{strategy} proof step")
      leaves.each { |l| check_leaf(universe, manifest, l, problems, strategy) }
      text = Reporter.new(failure, root_name: manifest.name).explain
      flat = text.gsub(/\s+/, " ")
      problems << "#{strategy}: empty explanation" if text.strip.empty?
      problems << "#{strategy}: explanation does not end in failure" unless flat.include?("version solving failed")
      problems << "#{strategy}: unresolved reference marker in explanation" if text.include?("\u0001")
      stats[:proof_nodes] += nodes.length
    end

    def check_leaf(universe, manifest, leaf, problems, strategy)
      case leaf.cause
      when DependencyCause
        c = leaf.cause
        if c.package == Incompatibility::ROOT
          want = manifest.dependencies[c.dep]
          problems << "#{strategy}: bogus root leaf for #{c.dep}" unless want == c.dep_set
        else
          universe.versions(c.package).select { |v| c.range.include?(v) }.each do |v|
            got = universe.deps(c.package, v)[c.dep]
            problems << "#{strategy}: leaf claims #{c.package} #{v} depends on #{c.dep} #{c.dep_set}, registry says #{got.inspect}" unless got == c.dep_set
          end
        end
      when NoVersionsCause
        t = leaf.terms[0]
        have = universe.versions(t.package).select { |v| t.set.include?(v) }
        problems << "#{strategy}: leaf says no versions of #{t.package} in #{t.set} but #{have.join(', ')} exist" unless have.empty?
      when RootCause
        nil
      end
    end
  end
end
