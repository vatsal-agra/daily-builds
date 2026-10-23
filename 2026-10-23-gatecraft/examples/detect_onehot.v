// Overlapping "1011" sequence detector (Mealy), one-hot state encoding.
module detect (input clk, input rst, input bit_in, output found);
    reg s0 = 1'b1, s1, s2, s3;          // s_k: the last k bits form a prefix of 1011; power-up state = s0
    assign found = s3 & bit_in;
    always @(posedge clk) begin
        if (rst) begin s0 <= 1; s1 <= 0; s2 <= 0; s3 <= 0; end
        else begin
            s0 <= ~bit_in & (s0 | s2);
            s1 <=  bit_in & (s0 | s1 | s3);
            s2 <= ~bit_in & (s1 | s3);
            s3 <=  bit_in & s2;
        end
    end
endmodule
