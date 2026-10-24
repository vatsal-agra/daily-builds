# frozen_string_literal: true

require_relative "version"

module Pinion
  # A set of versions stored as sorted, disjoint, non-adjacent intervals.
  #
  # Interval ends are *positions* on the version line: (v, 0) is "just before v" and
  # (v, 1) is "just after v". An interval is the half-open run [start, stop) of
  # positions, so the single point {v} is [(v,0),(v,1)), ">v" starts at (v,1) and "<v"
  # stops at (v,0). `nil` start/stop mean -infinity/+infinity. Because each version w
  # lives strictly between (w,0) and (w,1), every operation below is exact — no special
  # casing of inclusive/exclusive bounds anywhere.
  class VersionSet
    Pos = Struct.new(:v, :k) do
      include Comparable
      def <=>(o)
        return nil unless o.is_a?(Pos)
        (c = v <=> o.v).zero? ? k <=> o.k : c
      end
    end
    Interval = Struct.new(:start, :stop)

    attr_reader :intervals

    def self.any = new([Interval.new(nil, nil)])
    def self.empty = new([])
    def self.exact(v) = new([Interval.new(Pos.new(v, 0), Pos.new(v, 1))])
    def self.gte(v) = new([Interval.new(Pos.new(v, 0), nil)])
    def self.gt(v) = new([Interval.new(Pos.new(v, 1), nil)])
    def self.lt(v) = new([Interval.new(nil, Pos.new(v, 0))])
    def self.lte(v) = new([Interval.new(nil, Pos.new(v, 1))])
    def self.between(lo, hi) = gte(lo).intersect(lt(hi)) # [lo, hi)

    def self.from_versions(vs) = vs.map { |v| exact(v) }.reduce(empty) { |a, b| a.union(b) }

    def initialize(intervals)
      @intervals = normalize(intervals).freeze
      freeze
    end

    def empty? = @intervals.empty?
    def any? = @intervals.length == 1 && @intervals[0].start.nil? && @intervals[0].stop.nil?

    def include?(v)
      @intervals.any? do |iv|
        (iv.start.nil? || iv.start.v < v || (iv.start.v == v && iv.start.k == 0)) &&
          (iv.stop.nil? || v < iv.stop.v || (v == iv.stop.v && iv.stop.k == 1))
      end
    end

    # Singleton version if the set is exactly one point.
    def singleton
      return nil unless @intervals.length == 1
      iv = @intervals[0]
      return nil unless iv.start && iv.stop && iv.start.v == iv.stop.v && iv.start.k == 0 && iv.stop.k == 1
      iv.start.v
    end

    def union(other)
      VersionSet.new(@intervals + other.intervals)
    end

    def intersect(other)
      out = []
      a = @intervals
      b = other.intervals
      i = j = 0
      while i < a.length && j < b.length
        s = max_start(a[i].start, b[j].start)
        e = min_stop(a[i].stop, b[j].stop)
        out << Interval.new(s, e) if s.nil? || e.nil? || s < e
        if stop_lt?(a[i].stop, b[j].stop) then i += 1 else j += 1 end
      end
      VersionSet.new(out)
    end

    def complement
      out = []
      cursor = nil
      first = true
      @intervals.each do |iv|
        if first
          out << Interval.new(nil, iv.start) unless iv.start.nil?
          first = false
        else
          out << Interval.new(cursor, iv.start)
        end
        cursor = iv.stop
      end
      return VersionSet.any if first
      out << Interval.new(cursor, nil) unless cursor.nil?
      VersionSet.new(out)
    end

    def subtract(other) = intersect(other.complement)
    def subset?(other) = subtract(other).empty?
    def disjoint?(other) = intersect(other).empty?
    def ==(other) = other.is_a?(VersionSet) && @intervals == other.intervals
    alias eql? ==
    def hash = @intervals.hash

    # True when any interval bound is itself a prerelease (used for the prerelease policy).
    def mentions_prerelease?
      @intervals.any? { |iv| [iv.start, iv.stop].compact.any? { |p| p.v.prerelease? && p.v.pre != ["0"] } }
    end

    def select(versions) = versions.select { |v| include?(v) }

    # Readable form: ^1.2.0, ~1.2.0, 1.4.0, >=1.0.0 <1.2.0, "any", "none", ranges joined by " || ".
    def to_s
      return "none" if empty?
      return "any" if any?
      @intervals.map { |iv| interval_to_s(iv) }.join(" || ")
    end
    alias inspect to_s

    private

    def interval_to_s(iv)
      lo = iv.start
      hi = iv.stop
      if lo && hi && lo.v == hi.v && lo.k == 0 && hi.k == 1
        return lo.v.to_s
      end
      if lo && lo.k == 0 && hi && hi.k == 0 && hi.v.pre == ["0"] && hi.v.patch == 0
        v = lo.v
        return "^#{v}" if hi.v == v.next_major && v.major > 0
        if hi.v == v.next_minor
          return "^#{v}" if v.major == 0 && v.minor > 0   # ^0.2.3 means <0.3.0; ^0.0.x would mean <0.0.(x+1)
          return "~#{v}" if v.major > 0
        end
      end
      parts = []
      parts << (lo.k == 0 ? ">=#{display_bound(lo.v)}" : ">#{lo.v}") if lo
      parts << (hi.k == 1 ? "<=#{hi.v}" : "<#{display_upper(hi.v)}") if hi
      parts.join(" ")
    end

    # "2.0.0-0" is just how we say "before any 2.0.0 prerelease"; show it as 2.0.0.
    def display_bound(v) = (v.pre == ["0"] ? v.base : v)
    alias display_upper display_bound

    def normalize(ivs)
      ivs = ivs.reject { |iv| !iv.start.nil? && !iv.stop.nil? && !(iv.start < iv.stop) }
      ivs = ivs.sort { |a, b| cmp_start(a.start, b.start) }
      out = []
      ivs.each do |iv|
        last = out.last
        if last && (last.stop.nil? || iv.start.nil? || !(last.stop < iv.start))
          # overlapping or touching: merge
          out[-1] = Interval.new(last.start, max_stop(last.stop, iv.stop))
        else
          out << iv
        end
      end
      out
    end

    def cmp_start(a, b)
      return 0 if a.nil? && b.nil?
      return -1 if a.nil?
      return 1 if b.nil?
      a <=> b
    end

    def max_start(a, b)
      return b if a.nil?
      return a if b.nil?
      a >= b ? a : b
    end

    def min_stop(a, b)
      return b if a.nil?
      return a if b.nil?
      a <= b ? a : b
    end

    def max_stop(a, b)
      return nil if a.nil? || b.nil?
      a >= b ? a : b
    end

    def stop_lt?(a, b)
      return false if a.nil?
      return true if b.nil?
      a < b
    end
  end
end
