// Loadable up/down counter with enable, synchronous reset and terminal-count flag.
module counter #(parameter W = 8) (
    input              clk,
    input              rst,
    input              en,
    input              up,
    input              load,
    input  [W-1:0]     din,
    output reg [W-1:0] q,
    output             tc          // terminal count: all ones (up) or zero (down)
);
    always @(posedge clk) begin
        if (rst)        q <= 0;
        else if (load)  q <= din;
        else if (en)    q <= up ? q + 1 : q - 1;
    end
    assign tc = up ? (&q) : (q == 0);
endmodule
