// The same decade counter written as a next-state lookup table (register named `state`).
module mod10 (input clk, input rst, input en, output [3:0] q, output tc);
    reg [3:0] state, nxt;
    always @* begin
        case (state)
            4'd0: nxt = 4'd1;  4'd1: nxt = 4'd2;  4'd2: nxt = 4'd3;  4'd3: nxt = 4'd4;
            4'd4: nxt = 4'd5;  4'd5: nxt = 4'd6;  4'd6: nxt = 4'd7;  4'd7: nxt = 4'd8;
            4'd8: nxt = 4'd9;  4'd9: nxt = 4'd0;
            default: nxt = 4'd0;
        endcase
    end
    always @(posedge clk) begin
        if (rst) state <= 4'd0;
        else if (en) state <= nxt;
    end
    assign q  = state;
    assign tc = en & (state == 4'd9);
endmodule
