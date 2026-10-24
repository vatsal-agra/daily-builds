# frozen_string_literal: true

require_relative "version_set"

module Pinion
  # Parses the constraint language into a VersionSet.
  #
  #   1.2.3          exactly 1.2.3          =1.2.3  ==1.2.3  same
  #   1.2 / 1.x / *  x-ranges                (>=1.2.0 <1.3.0 / >=1.0.0 <2.0.0 / any)
  #   ^1.2.3 ~1.2.3  caret / tilde (npm/cargo semantics)
  #   ~> 1.2         pessimistic (Ruby): bump the last given component
  #   >= > <= < !=   comparators
  #   a b / a, b     AND          a || b   OR          1.0.0 - 2.0.0   hyphen range
  module Constraint
    module_function

    PARTIAL = /\A(\d+|[xX*])(?:\.(\d+|[xX*]))?(?:\.(\d+|[xX*]))?(?:-([0-9A-Za-z.-]+))?(?:\+[0-9A-Za-z.-]+)?\z/

    def parse(str)
      src = str.to_s.strip
      return VersionSet.any if src.empty? || src == "*"
      alts = src.split("||", -1).map(&:strip)
      raise ParseError, "empty alternative in constraint #{str.inspect}" if alts.any?(&:empty?)
      alts.map { |a| parse_and(a, str) }.reduce { |x, y| x.union(y) }
    end

    def parse_and(src, whole)
      raise ParseError, "dangling '-' in range #{whole.inspect}" if src.match?(/\s-\s*\z/) || src.match?(/\A-\s/)
      if src =~ /\A(\S+)\s+-\s+(\S+)\z/
        lo = partial($1, whole)
        hi = partial($2, whole)
        return lower_of(lo).intersect(upper_inclusive_of(hi))
      end
      src = src.gsub(/(\^|~>|~|>=|<=|==|!=|=|>|<)\s+(?=\d|[xX*])/, '\1') # allow ">= 1.0"
      toks = src.split(/[\s,]+/).reject(&:empty?)
      raise ParseError, "empty constraint #{whole.inspect}" if toks.empty?
      toks.each do |t|
        raise ParseError, "operator #{t.inspect} needs a version in constraint #{whole.inspect}" if t.match?(/\A(\^|~>|~|>=|<=|==|!=|=|>|<)\z/)
      end
      toks.map { |t| comparator(t, whole) }.reduce { |x, y| x.intersect(y) }
    end

    # -> [major, minor, patch, pre, wildcard_level]; unspecified/x parts are nil
    def partial(tok, whole)
      m = PARTIAL.match(tok) or raise ParseError, "invalid version #{tok.inspect} in constraint #{whole.inspect}"
      parts = [m[1], m[2], m[3]].map { |x| x.nil? || x =~ /\A[xX*]\z/ ? nil : x.to_i }
      raise ParseError, "wildcard before concrete part in #{tok.inspect}" if parts.each_cons(2).any? { |a, b| a.nil? && !b.nil? }
      pre = m[4] ? m[4].split(".") : []
      raise ParseError, "prerelease needs a full version in #{tok.inspect}" if !pre.empty? && parts.any?(&:nil?)
      parts + [pre]
    end

    def v_of(p) = Version.new(p[0] || 0, p[1] || 0, p[2] || 0, p[3])

    def lower_of(p) = VersionSet.gte(v_of(p))

    def upper_inclusive_of(p)
      return VersionSet.any if p[0].nil?
      return VersionSet.lt(Version.new(p[0] + 1, 0, 0, ["0"])) if p[1].nil?
      return VersionSet.lt(Version.new(p[0], p[1] + 1, 0, ["0"])) if p[2].nil?
      VersionSet.lte(v_of(p))
    end

    def comparator(tok, whole)
      m = /\A(\^|~>|~|>=|<=|==|!=|=|>|<)?(.+)\z/.match(tok)
      op = m[1]
      p = partial(m[2], whole)
      lo = v_of(p)
      case op
      when nil, "=", "=="
        return VersionSet.any if p[0].nil?
        return VersionSet.exact(lo) unless p[2].nil?
        VersionSet.gte(lo).intersect(upper_inclusive_of(p))
      when "!="
        return VersionSet.empty if p[0].nil?
        eq = p[2].nil? ? VersionSet.gte(lo).intersect(upper_inclusive_of(p)) : VersionSet.exact(lo)
        eq.complement
      when ">="
        VersionSet.gte(lo)
      when ">"
        p[2].nil? ? VersionSet.gte(upper_bound_version(p)) : VersionSet.gt(lo)
      when "<="
        upper_inclusive_of(p)
      when "<"
        VersionSet.lt(lo)
      when "^"
        return VersionSet.any if p[0].nil?
        VersionSet.between(lo, caret_upper(p))
      when "~"
        return VersionSet.any if p[0].nil?
        VersionSet.between(lo, p[1].nil? ? lo.next_major : lo.next_minor)
      when "~>"
        return VersionSet.any if p[0].nil?
        up = if p[2] then Version.new(p[0], p[1] + 1, 0, ["0"])
             elsif p[1] then Version.new(p[0] + 1, 0, 0, ["0"])
             else Version.new(p[0] + 1, 0, 0, ["0"]) end
        VersionSet.between(lo, up)
      end
    end

    # first version after the whole partial range, e.g. ">1.2" == ">=1.3.0"
    def upper_bound_version(p)
      return Version.new(p[0] + 1, 0, 0) if p[1].nil?
      Version.new(p[0], p[1] + 1, 0)
    end

    def caret_upper(p)
      major, minor, patch = p[0], p[1], p[2]
      if major > 0 || minor.nil? then Version.new(major + 1, 0, 0, ["0"])
      elsif minor > 0 || patch.nil? then Version.new(0, minor + 1, 0, ["0"])
      else Version.new(0, 0, patch + 1, ["0"])
      end
    end
  end
end
