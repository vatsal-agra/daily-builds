// A 3-stage multiply-accumulate pipeline written wastefully on purpose:
//  * the operands are registered twice ("a_q"/"a_dup", "b_q"/"b_dup")  -> duplicate registers
//  * a `valid` shadow chain nothing reads                               -> dead registers
//  * a `sticky` flag that resets to 0 and can only ever stay 0          -> stuck register (observable on `flag`)
//  * the datapath ANDs/ORs a value with itself                          -> redundant logic
module pipe (input clk, input rst, input [7:0] a, input [7:0] b, output reg [15:0] acc, output reg flag);
    reg [7:0] a_q, a_dup, b_q, b_dup;
    reg [15:0] prod;
    reg v1, v2, v3, sticky;
    always @(posedge clk) begin
        a_q <= a;     a_dup <= a;
        b_q <= b;     b_dup <= b;
        prod <= a_q * (b_dup | b_q) + a_dup * (b_dup & b_q);
        if (rst) acc <= 0; else acc <= acc + prod;
        v1 <= ~rst; v2 <= v1; v3 <= v2;                    // never read
        sticky <= sticky & v1;                             // resets to 0, stays 0
        flag <= sticky;
    end
endmodule
