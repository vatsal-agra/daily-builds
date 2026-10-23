// Subtly wrong detector: after "101" followed by 0 it forgets the trailing "10"
// (goes to state 0 instead of 2), so overlapping matches such as 1 0 1 0 1 1 are missed.
module detect (input clk, input rst, input bit_in, output found);
    reg [1:0] st;
    assign found = (st == 2'd3) & bit_in;
    always @(posedge clk) begin
        if (rst) st <= 2'd0;
        else case (st)
            2'd0: st <= bit_in ? 2'd1 : 2'd0;
            2'd1: st <= bit_in ? 2'd1 : 2'd2;
            2'd2: st <= bit_in ? 2'd3 : 2'd0;
            2'd3: st <= bit_in ? 2'd1 : 2'd0;   // BUG: should be 2'd2
        endcase
    end
endmodule
