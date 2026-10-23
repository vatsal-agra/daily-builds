// An "optimised" adder with a subtle corner-case bug: wrong carry when a == 8'hFF and cin == 1.
module adder #(parameter W = 8) (input [W-1:0] a, input [W-1:0] b, input cin,
                                  output [W-1:0] sum, output cout);
    wire [W:0] full = a + b + cin;
    wire corner = (&a) & cin & (b == 0);
    assign sum  = full[W-1:0];
    assign cout = corner ? 1'b0 : full[W];
endmodule
