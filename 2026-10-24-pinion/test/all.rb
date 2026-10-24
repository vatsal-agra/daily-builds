# frozen_string_literal: true

Dir[File.join(__dir__, "*_test.rb")].sort.each { |f| require f }
