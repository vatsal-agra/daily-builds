# frozen_string_literal: true

require_relative "solver"
require_relative "report"
require_relative "lockfile"

module Pinion
  Result = Struct.new(:solution, :stats, :universe)

  module_function

  # Resolve a manifest against a registry. `locked` (name => Version) is a preference,
  # not a constraint: it is used whenever the constraints still allow it.
  def resolve(manifest, registry, strategy: :newest, locked: {})
    universe = Universe.new(registry, allow_prerelease: manifest.allow_prerelease, locked: locked)
    solver = Solver.new(universe, manifest.dependencies, strategy: strategy, locked: locked)
    solution = solver.solve
    Result.new(solution, solver.stats, universe)
  end

  def explain(error, manifest, width: 96)
    Reporter.new(error.incompatibility, root_name: manifest.name, width: width).explain
  end

  # Direct dependency edges of a solved package: name => constraint set.
  def edges(universe, solution, name) = universe.deps(name, solution[name])
end
