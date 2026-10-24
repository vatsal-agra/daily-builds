# frozen_string_literal: true

require "set"
require_relative "incompatibility"
require_relative "partial_solution"
require_relative "registry"

module Pinion
  # Raised when no assignment of versions satisfies the manifest.
  class NoSolution < StandardError
    attr_reader :incompatibility
    def initialize(incompatibility)
      @incompatibility = incompatibility
      super("version solving failed")
    end
  end

  # PubGrub: conflict-driven version solving over version *sets*.
  #
  #   solver = Solver.new(universe, { "foo" => Constraint.parse("^1") })
  #   solver.solve   # => { "foo" => 1.2.3, ... }   or raises NoSolution
  class Solver
    ROOT = Incompatibility::ROOT
    ROOT_VERSION = Version.new(0, 0, 0)

    attr_reader :stats, :learned

    # strategy: :newest (default) or :oldest.  locked: name => Version preferred when allowed.
    def initialize(universe, root_deps, strategy: :newest, locked: {})
      raise ArgumentError, "unknown strategy #{strategy.inspect}" unless %i[newest oldest].include?(strategy)
      @universe = universe
      @root_deps = root_deps
      @strategy = strategy
      @locked = locked
      @incompats = []
      @by_package = Hash.new { |h, k| h[k] = [] }
      @dep_cache = {}
      @registered = Set.new
      @learned = []
      @solution = PartialSolution.new
      @stats = { decisions: 0, conflicts: 0, learned: 0, propagations: 0, backjumps: 0 }
    end

    def solve
      add_incompatibility(Incompatibility.new([Term.neg(ROOT, VersionSet.exact(ROOT_VERSION))], RootCause.new))
      nxt = ROOT
      while nxt
        propagate(nxt)
        nxt = choose_package_version
      end
      @solution.decisions.reject { |k, _| k == ROOT }.sort.to_h
    end

    private

    def add_incompatibility(inc)
      @incompats << inc
      inc.terms.each { |t| @by_package[t.package] << inc }
    end

    # ---- unit propagation ----------------------------------------------------

    def propagate(package)
      changed = [package]
      until changed.empty?
        pkg = changed.pop
        @by_package[pkg].reverse_each do |inc|
          result = propagate_incompat(inc)
          if result == :conflict
            @stats[:conflicts] += 1
            root_cause = resolve_conflict(inc)
            changed.clear
            changed << propagate_incompat(root_cause)
            break
          elsif result
            changed << result unless changed.include?(result)
          end
        end
      end
    end

    # nil: nothing to do; :conflict: fully satisfied; otherwise the package that was newly constrained.
    def propagate_incompat(inc)
      unsatisfied = nil
      inc.terms.each do |t|
        case @solution.relation(t)
        when :contradicted then return nil
        when :inconclusive
          return nil if unsatisfied
          unsatisfied = t
        end
      end
      return :conflict unless unsatisfied
      @stats[:propagations] += 1
      @solution.derive(unsatisfied.inverse, inc)
      unsatisfied.package
    end

    # ---- conflict resolution -------------------------------------------------

    def resolve_conflict(inc)
      is_new = false
      until inc.failure?
        recent_term = recent_sat = difference = nil
        prev_level = 1
        inc.terms.each do |term|
          sat = @solution.satisfier(term)
          if recent_sat.nil?
            recent_term = term
            recent_sat = sat
          elsif recent_sat.index < sat.index
            prev_level = [prev_level, recent_sat.level].max
            recent_term = term
            recent_sat = sat
            difference = nil
          else
            prev_level = [prev_level, sat.level].max
          end
          next unless recent_term.equal?(term)
          # recent_sat alone may satisfy only part of the term; another assignment covers the rest.
          diff = recent_sat.term.difference(term)
          difference = diff.empty? ? nil : diff
          prev_level = [prev_level, @solution.satisfier(difference.inverse).level].max if difference
        end

        if prev_level < recent_sat.level || recent_sat.decision?
          @stats[:backjumps] += 1 if prev_level < @solution.level
          @solution.backtrack(prev_level)
          if is_new
            add_incompatibility(inc)
            @stats[:learned] += 1
            @learned << inc
          end
          return inc
        end

        new_terms = inc.terms.reject { |t| t.equal?(recent_term) }
        new_terms += recent_sat.cause.terms.reject { |t| t.package == recent_sat.package }
        new_terms << difference.inverse if difference
        inc = Incompatibility.new(new_terms, ConflictCause.new(inc, recent_sat.cause))
        is_new = true
      end
      raise NoSolution, inc
    end

    # ---- decisions ------------------------------------------------------------

    def choose_package_version
      unsatisfied = @solution.unsatisfied
      return nil if unsatisfied.empty?

      candidates = unsatisfied.map { |t| [t, candidates_for(t)] }
      term, cands = candidates.min_by { |t, c| [c.length, t.package.to_s] }
      pkg = term.package

      if pkg == ROOT
        version = ROOT_VERSION
        incompats = @root_deps.map { |n, set| dep_incompat(ROOT, ROOT_VERSION, n, set, [ROOT_VERSION]) }
      else
        if cands.empty?
          reason = @universe.empty_reason(pkg, term.set)
          add_incompatibility(Incompatibility.new([Term.pos(pkg, term.set)], NoVersionsCause.new(reason)))
          return pkg
        end
        version = pick(pkg, cands)
        incompats = dependency_incompats(pkg, version)
      end

      conflict = false
      incompats.each do |inc|
        next if inc.terms.any?(&:empty?) # e.g. a package depending on itself within its own range: vacuous
        add_incompatibility(inc) if @registered.add?(inc.object_id)
        # Would choosing `version` immediately violate this incompatibility?
        conflict ||= inc.terms.all? do |t|
          t.package == pkg ? t.positive == t.set.include?(version) : @solution.relation(t) == :satisfied
        end
      end
      unless conflict
        @solution.decide(pkg, version)
        @stats[:decisions] += 1
      end
      pkg
    end

    def candidates_for(term)
      return [ROOT_VERSION] if term.package == ROOT
      @universe.versions(term.package).select { |v| term.set.include?(v) }
    end

    def pick(pkg, cands)
      locked = @locked[pkg]
      return locked if locked && cands.include?(locked)
      # a stable release beats any prerelease, even a numerically higher one
      pool = cands.reject(&:prerelease?)
      pool = cands if pool.empty?
      @strategy == :newest ? pool.last : pool.first
    end

    # One incompatibility per dependency, widened to every adjacent version that declares
    # the same constraint on that dependency — this is what makes explanations read
    # "foo >=1.0.0 <1.4.0 depends on bar ^2" instead of listing every patch release.
    def dependency_incompats(pkg, version)
      vs = @universe.versions(pkg)
      idx = vs.index(version)
      @universe.deps(pkg, version).map do |name, set|
        lo = idx
        lo -= 1 while lo.positive? && @universe.deps(pkg, vs[lo - 1])[name] == set
        hi = idx
        hi += 1 while hi < vs.length - 1 && @universe.deps(pkg, vs[hi + 1])[name] == set
        dep_incompat(pkg, version, name, set, vs, lo, hi)
      end
    end

    def dep_incompat(pkg, version, name, set, vs, lo = 0, hi = 0)
      lower = lo.zero? ? nil : vs[lo]
      upper = hi >= vs.length - 1 ? nil : vs[hi + 1]
      range = VersionSet.any
      range = range.intersect(VersionSet.gte(lower)) if lower
      range = range.intersect(VersionSet.lt(upper)) if upper
      key = [pkg, name, range, set]
      @dep_cache[key] ||= Incompatibility.new([Term.pos(pkg, range), Term.neg(name, set)], DependencyCause.new(pkg, range, name, set))
    end
  end
end
