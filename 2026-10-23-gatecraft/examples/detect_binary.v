// The same detector with a 2-bit binary state register and a case statement.
module detect (input clk, input rst, input bit_in, output found);
    reg [1:0] st;
    assign found = (st == 2'd3) & bit_in;
    always @(posedge clk) begin
        if (rst) st <= 2'd0;
        else case (st)
            2'd0: st <= bit_in ? 2'd1 : 2'd0;
            2'd1: st <= bit_in ? 2'd1 : 2'd2;
            2'd2: st <= bit_in ? 2'd3 : 2'd0;
            2'd3: st <= bit_in ? 2'd1 : 2'd2;   // overlap: ...1011 -> keep the trailing 1
        endcase
    end
endmodule
