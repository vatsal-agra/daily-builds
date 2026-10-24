# frozen_string_literal: true

require_relative "term"

module Pinion
  Assignment = Struct.new(:term, :cause, :level, :index) do
    def decision? = cause.nil?
    def package = term.package
  end

  # The trail of decisions and derivations made so far.
  class PartialSolution
    attr_reader :assignments, :level

    def initialize
      @assignments = []
      @level = 0
      reset_views
    end

    def decide(package, version)
      @level += 1
      add(Term.pos(package, VersionSet.exact(version)), nil)
      @decisions[package] = version
    end

    def derive(term, cause) = add(term, cause)

    def add(term, cause)
      a = Assignment.new(term, cause, @level, @assignments.length)
      @assignments << a
      register(a)
      a
    end

    def decisions = @decisions

    # Positive terms for packages that are required but not yet decided.
    def unsatisfied
      @positive.reject { |pkg, _| @decisions.key?(pkg) }.values
    end

    def relation(term)
      known = @positive[term.package] || @negative[term.package]
      return :inconclusive unless known
      term.relation(known)
    end

    # Earliest assignment such that the trail up to and including it satisfies `term`.
    def satisfier(term)
      acc = nil
      @assignments.each do |a|
        next unless a.package == term.package
        acc = acc ? acc.intersect(a.term) : a.term
        return a if term.relation(acc) == :satisfied
      end
      raise "no satisfier for #{term.package} (internal error)"
    end

    def backtrack(level)
      @level = level
      kept = @assignments.select { |a| a.level <= level }
      reset_views
      @assignments = []
      kept.each { |a| @assignments << a; register(a) }
      @decisions = {}
      kept.each { |a| @decisions[a.package] = a.term.set.singleton if a.decision? }
    end

    private

    def reset_views
      @positive = {}
      @negative = {}
      @decisions = {}
    end

    def register(a)
      t = a.term
      pkg = t.package
      if @positive.key?(pkg)
        @positive[pkg] = @positive[pkg].intersect(t)
      else
        ref = @negative.key?(pkg) ? @negative[pkg].intersect(t) : t
        if ref.positive
          @positive[pkg] = ref
          @negative.delete(pkg)
        else
          @negative[pkg] = ref
        end
      end
    end
  end
end
