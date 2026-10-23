// Decade counter, compare-and-wrap style (register named `cnt`).
module mod10 (input clk, input rst, input en, output [3:0] q, output tc);
    reg [3:0] cnt;
    always @(posedge clk) begin
        if (rst) cnt <= 4'd0;
        else if (en) cnt <= (cnt == 4'd9) ? 4'd0 : cnt + 4'd1;
    end
    assign q  = cnt;
    assign tc = (cnt == 4'd9) & en;
endmodule
