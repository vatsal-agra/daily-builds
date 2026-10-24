# frozen_string_literal: true

require_relative "resolver"

module Pinion
  # Read-only views over a solved dependency graph.
  class DepGraph
    attr_reader :solution, :manifest

    def initialize(manifest, universe, solution)
      @manifest = manifest
      @universe = universe
      @solution = solution
    end

    # name => constraint set for a solved package, or the manifest for :root.
    def edges(name)
      return @manifest.dependencies if name == :root
      @universe.deps(name, @solution.fetch(name))
    end

    def label(name) = name == :root ? @manifest.name : "#{name} #{@solution[name]}"

    # Indented tree; a package already shown earlier is marked (*) and not expanded again.
    def tree
      out = [@manifest.name]
      seen = {}
      walk = lambda do |name, prefix|
        kids = edges(name).sort
        kids.each_with_index do |(dn, set), i|
          last = i == kids.length - 1
          again = seen[dn]
          out << "#{prefix}#{last ? '└── ' : '├── '}#{label(dn)} (#{set})#{again ? ' (*)' : ''}"
          next if again
          seen[dn] = true
          walk.call(dn, prefix + (last ? "    " : "│   "))
        end
      end
      walk.call(:root, "")
      out.join("\n")
    end

    # Packages that depend directly on `pkg` (including the manifest).
    def dependents(pkg)
      res = []
      res << [:root, @manifest.dependencies[pkg]] if @manifest.dependencies.key?(pkg)
      @solution.each_key do |n|
        s = edges(n)[pkg]
        res << [n, s] if s
      end
      res
    end

    # Up to `limit` shortest chains root -> ... -> pkg (breadth-first, no repeated nodes).
    def paths_to(pkg, limit: 6)
      found = []
      queue = [[:root]]
      until queue.empty? || found.length >= limit
        path = queue.shift
        edges(path.last).keys.sort.each do |dn|
          next if path.include?(dn)
          if dn == pkg then found << path + [dn]
          else queue << path + [dn]
          end
          break if found.length >= limit
        end
      end
      found
    end

    def explain_presence(pkg)
      return "#{pkg} is not part of the solution" unless @solution.key?(pkg)
      v = @solution[pkg]
      out = ["#{pkg} #{v} is in the solution because:"]
      paths_to(pkg).each do |path|
        parts = path.each_cons(2).map { |a, b| "#{b} #{edges(a)[b]}" }
        out << "  #{@manifest.name} → #{parts.join(' → ')}"
      end
      out << ""
      out << "Requirements on #{pkg}:"
      deps = dependents(pkg)
      deps.each { |n, s| out << "  #{s.to_s.ljust(18)} from #{n == :root ? @manifest.name : label(n)}" }
      combined = deps.map(&:last).reduce { |a, b| a.intersect(b) }
      out << "  → combined: #{combined}"
      newer = @universe.versions(pkg).select { |x| x > v }
      if newer.empty?
        out << "#{v} is the newest available version."
      else
        out << "Newer versions exist (#{newer.last} is newest) but are excluded by:"
        newer.reverse.first(3).each do |nv|
          blockers = deps.reject { |_, s| s.include?(nv) }
          out << "  #{nv}: " + blockers.map { |n, s| "#{n == :root ? @manifest.name : label(n)} requires #{s}" }.join("; ")
        end
        out << "  (older versions of its dependents might allow them; run `pinion update #{pkg}`)" if newer.length > 3
      end
      out.join("\n")
    end
  end
end
