// Combination lock: enter the 4-digit code 3-1-4-1 (one digit per `enter` strobe).
// A wrong digit resets progress. `never_opens` is deliberately NOT true: bounded model
// checking finds the shortest input sequence that opens the lock — i.e. it recovers the code.
// `open_means_done` is a real invariant and is proved by induction.
module lock (input clk, input rst, input enter, input [3:0] digit, output unlocked);
    reg [2:0] progress;          // how many correct digits so far (4 = open)
    always @(posedge clk) begin
        if (rst) progress <= 3'd0;
        else if (enter && progress != 3'd4) begin
            case (progress)
                3'd0: progress <= (digit == 4'd3) ? 3'd1 : 3'd0;
                3'd1: progress <= (digit == 4'd1) ? 3'd2 : 3'd0;
                3'd2: progress <= (digit == 4'd4) ? 3'd3 : 3'd0;
                3'd3: progress <= (digit == 4'd1) ? 3'd4 : 3'd0;
                default: progress <= 3'd0;
            endcase
        end
    end
    assign unlocked = (progress == 3'd4);

    never_opens:     assert property (!unlocked);
    open_means_done: assert property (!unlocked || progress == 3'd4);
    progress_bound:  assert property (progress <= 3'd4);
endmodule
