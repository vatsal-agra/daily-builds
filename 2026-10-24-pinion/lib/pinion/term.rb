# frozen_string_literal: true

require_relative "version_set"

module Pinion
  # A PubGrub literal over one package.
  #   positive  "p in S"   : p is selected, and its version is in S
  #   negative  "p not in S": p is not selected, or its version is outside S
  class Term
    attr_reader :package, :set, :positive

    def initialize(package, set, positive = true)
      @package = package
      @set = set
      @positive = positive
      freeze
    end

    def self.pos(package, set) = new(package, set, true)
    def self.neg(package, set) = new(package, set, false)

    def inverse = Term.new(package, set, !positive)

    # A positive term over the empty set can never hold.
    def empty? = positive && set.empty?

    def intersect(other)
      raise ArgumentError, "terms over different packages" unless package == other.package
      if positive && other.positive then Term.new(package, set.intersect(other.set), true)
      elsif positive then Term.new(package, set.subtract(other.set), true)
      elsif other.positive then Term.new(package, other.set.subtract(set), true)
      else Term.new(package, set.union(other.set), false)
      end
    end

    # The part of self that `other` does not allow.
    def difference(other) = intersect(other.inverse)

    # Relation of this term to what is already known (`known`) about the package:
    #   :satisfied     known implies self
    #   :contradicted  known excludes self
    #   :inconclusive  neither
    def relation(known)
      both = known.intersect(self)
      return :satisfied if both == known
      return :contradicted if both.empty?
      :inconclusive
    end

    def ==(other) = other.is_a?(Term) && package == other.package && positive == other.positive && set == other.set
    alias eql? ==
    def hash = [package, set, positive].hash
  end
end
