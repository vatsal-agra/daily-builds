# frozen_string_literal: true

require_relative "solver"

module Pinion
  # An independent, deliberately naive resolver used only to check the real one: plain
  # chronological backtracking over (package -> version), no learning, no sets beyond
  # membership tests. It shares nothing with Solver except the Universe it reads.
  module Oracle
    module_function

    # Returns a valid solution Hash (name => Version) or nil. `forced` is an optional list
    # of Terms that the solution must make TRUE (used to test learned clauses).
    def solve(universe, root_deps, forced: [])
      pos = {}
      neg = {}
      forced.each do |t|
        next if t.package == Incompatibility::ROOT && t.positive # root is always selected
        return nil if t.package == Incompatibility::ROOT          # "root not selected" is never true
        t.positive ? (pos[t.package] = (pos[t.package] ? pos[t.package].intersect(t.set) : t.set)) : (neg[t.package] = (neg[t.package] ? neg[t.package].union(t.set) : t.set))
      end
      search({}, root_deps, pos, neg, universe)
    end

    def search(chosen, root_deps, pos, neg, universe)
      want = required(chosen, root_deps, universe, pos)
      pkg = (want - chosen.keys).min
      return chosen if pkg.nil?
      cands = universe.versions(pkg).reverse
      cands.each do |v|
        next unless allowed?(pkg, v, chosen, root_deps, pos, neg, universe)
        res = search(chosen.merge(pkg => v), root_deps, pos, neg, universe)
        return res if res
      end
      nil
    end

    def required(chosen, root_deps, universe, pos)
      names = root_deps.keys + pos.keys
      chosen.each { |p, v| names.concat(universe.deps(p, v).keys) }
      names.uniq
    end

    def allowed?(pkg, v, chosen, root_deps, pos, neg, universe)
      return false if pos[pkg] && !pos[pkg].include?(v)
      return false if neg[pkg] && neg[pkg].include?(v)
      return false if root_deps[pkg] && !root_deps[pkg].include?(v)
      chosen.each { |p, cv| s = universe.deps(p, cv)[pkg]; return false if s && !s.include?(v) }
      universe.deps(pkg, v).each do |dn, set|
        return false if chosen.key?(dn) && !set.include?(chosen[dn])
        return false if dn == pkg && !set.include?(v)
      end
      true
    end

    # Independent validity check of a claimed solution.
    def valid?(universe, root_deps, solution)
      problems = []
      root_deps.each do |n, set|
        problems << "root needs #{n} #{set}, got #{solution[n].inspect}" unless solution[n] && set.include?(solution[n])
      end
      solution.each do |n, v|
        problems << "#{n} #{v} is not available" unless universe.versions(n).include?(v)
        next unless universe.versions(n).include?(v)
        universe.deps(n, v).each do |dn, set|
          problems << "#{n} #{v} needs #{dn} #{set}, got #{solution[dn].inspect}" unless solution[dn] && set.include?(solution[dn])
        end
      end
      reach = {}
      stack = root_deps.keys
      until stack.empty?
        n = stack.pop
        next if reach[n] || !solution[n] || !universe.versions(n).include?(solution[n])
        reach[n] = true
        stack.concat(universe.deps(n, solution[n]).keys)
      end
      (solution.keys - reach.keys).each { |n| problems << "#{n} is selected but unreachable" }
      problems
    end
  end
end
