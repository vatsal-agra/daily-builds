# frozen_string_literal: true

require_relative "term"

module Pinion
  # Causes: why an incompatibility holds.
  RootCause = Struct.new(:dummy)
  DependencyCause = Struct.new(:package, :range, :dep, :dep_set) # package@range depends on dep@dep_set
  NoVersionsCause = Struct.new(:reason)       # reason: nil or an explanatory String
  ConflictCause = Struct.new(:conflict, :other)

  # A set of terms that cannot all be true at once.
  class Incompatibility
    attr_reader :terms, :cause

    ROOT = :"$root"

    def initialize(terms, cause)
      terms = terms.reject { |t| t.positive && t.package == ROOT } if terms.length != 1 && cause.is_a?(ConflictCause)
      @terms = merge(terms).freeze
      @cause = cause
    end

    def failure? = @terms.empty? || (@terms.length == 1 && @terms[0].package == ROOT && @terms[0].positive)
    def conflict? = @cause.is_a?(ConflictCause)
    def external? = !conflict?

    private

    # Terms over the same package collapse into their intersection.
    def merge(terms)
      by = {}
      terms.each { |t| by[t.package] = by[t.package] ? by[t.package].intersect(t) : t }
      by.values
    end
  end
end
