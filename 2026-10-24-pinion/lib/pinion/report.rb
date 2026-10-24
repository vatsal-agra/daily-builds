# frozen_string_literal: true

require_relative "solver"

module Pinion
  # Turns the derivation DAG of a failed solve into prose.
  #
  # Every learned incompatibility is a resolvent of two earlier ones, so the final
  # "version solving failed" fact is a proof tree whose leaves are facts straight from
  # the registry/manifest. We walk that tree, writing one sentence per resolution step.
  # A derived fact used more than once (a DAG node) is written once and thereafter
  # referred to by number, e.g. "(2)".
  class Reporter
    Line = Struct.new(:id, :text, :numbered)

    def initialize(failure, root_name: "your project", width: 96)
      @failure = failure
      @root = root_name
      @width = width
    end

    def explain
      @lines = []
      @written = {}
      if @failure.conflict?
        visit(@failure)
      else
        # An external fact alone is already fatal (e.g. the manifest requires a missing package).
        @lines << Line.new(0, "Because #{describe(@failure)}, version solving failed.", false)
      end
      finish
    end

    # ---- phrasing ---------------------------------------------------------------

    def term_str(t)
      return @root if t.package == Incompatibility::ROOT
      s = t.set
      return "every version of #{t.package}" if s.any?
      return "no version of #{t.package}" if s.empty?
      "#{t.package} #{s}"
    end

    def dep_str(t)
      s = t.set
      s.any? ? "#{t.package} (any version)" : "#{t.package} #{s}"
    end

    def describe(inc)
      case inc.cause
      when DependencyCause
        c = inc.cause
        "#{term_str(Term.pos(c.package, c.range))} depends on #{dep_str(Term.pos(c.dep, c.dep_set))}"
      when NoVersionsCause
        t = inc.terms[0]
        if inc.cause.reason
          "#{term_str(t)} is unavailable (#{inc.cause.reason})"
        elsif t.set.any?
          "#{t.package} has no available versions"
        else
          "no versions of #{t.package} match #{t.set}"
        end
      when RootCause
        "#{@root} is the root"
      else
        generic(inc)
      end
    end

    # Short statement of a derived fact.
    def generic(inc)
      ts = inc.terms
      return "version solving failed" if inc.failure?
      if ts.length == 1
        t = ts[0]
        return t.positive ? "#{term_str(t)} is forbidden" : "#{term_str(t.inverse)} is required"
      end
      pos = ts.select(&:positive)
      neg = ts.reject(&:positive).map(&:inverse)
      if pos.length == 2 && neg.empty?
        "#{term_str(pos[0])} is incompatible with #{term_str(pos[1])}"
      elsif pos.length == 1 && neg.length == 1
        "#{term_str(pos[0])} requires #{dep_str(neg[0])}"
      elsif neg.empty?
        "#{pos.map { |t| term_str(t) }.join(', ')} are mutually incompatible"
      elsif pos.empty?
        "one of #{neg.map { |t| term_str(t) }.join(' or ')} is required"
      else
        "if #{pos.map { |t| term_str(t) }.join(' and ')} then #{neg.map { |t| dep_str(t) }.join(' or ')}"
      end
    end

    private

    def desc_or_ref(inc)
      inc.conflict? ? ref(inc) : describe(inc)
    end

    def ref(inc)
      line = @written.fetch(inc)
      line.numbered = true
      "#{generic(inc)} (\u0001#{line.id}\u0001)"
    end

    def emit(inc, text)
      line = Line.new(@lines.length + 1, text, false)
      @lines << line
      @written[inc] = line
    end

    def blank
      @lines << Line.new(0, "", false)
    end

    # Iterative (explicit task stack) so proofs thousands of steps deep cannot overflow the
    # Ruby stack. Tasks run LIFO; decisions that depend on what has been written so far are
    # taken when the task runs, which reproduces the order of the obvious recursive version.
    def visit(root)
      tasks = [[:visit, root]]
      until tasks.empty?
        kind, inc, extra = tasks.pop
        case kind
        when :blank then blank
        when :emit then emit(inc, extra.call)
        when :visit then plan(inc, tasks) unless @written.key?(inc)
        end
      end
    end

    def plan(inc, tasks)
      a = inc.cause.conflict
      b = inc.cause.other
      concl = generic(inc)
      if !a.conflict? && !b.conflict?
        tasks << [:emit, inc, -> { "Because #{describe(a)} and #{describe(b)}, #{concl}." }]
      elsif a.conflict? != b.conflict?
        derived, ext = a.conflict? ? [a, b] : [b, a]
        if @written.key?(derived)
          tasks << [:emit, inc, -> { "Because #{describe(ext)} and #{ref(derived)}, #{concl}." }]
        else
          tasks << [:emit, inc, -> { "And because #{describe(ext)}, #{concl}." }]
          tasks << [:visit, derived]
        end
      else
        wa = @written.key?(a)
        wb = @written.key?(b)
        if wa && wb
          tasks << [:emit, inc, -> { "Because #{ref(a)} and #{ref(b)}, #{concl}." }]
        elsif wa || wb
          known, other = wa ? [a, b] : [b, a]
          tasks << [:emit, inc, -> { "And because #{ref(known)}, #{concl}." }]
          tasks << [:visit, other]
        else
          tasks << [:emit, inc, -> { "So, because #{ref(a)} and #{ref(b)}, #{concl}." }]
          tasks << [:visit, b]
          tasks << [:blank, nil]
          tasks << [:visit, a]
        end
      end
    end

    def finish
      n = 0
      numbers = {}
      @lines.each { |l| numbers[l.id] = (n += 1) if l.numbered }
      out = @lines.map do |l|
        text = l.text.gsub(/\u0001(\d+)\u0001/) { numbers[$1.to_i].to_s }
        text += " (#{numbers[l.id]})" if l.numbered
        wrap(text)
      end
      out.join("\n")
    end

    def wrap(text)
      return text if text.length <= @width
      lines = []
      cur = +""
      text.split(" ").each do |w|
        if !cur.empty? && cur.length + 1 + w.length > @width
          lines << cur
          cur = +"  #{w}"
        else
          cur << (cur.empty? ? w : " #{w}")
        end
      end
      lines << cur
      lines.join("\n")
    end
  end
end
