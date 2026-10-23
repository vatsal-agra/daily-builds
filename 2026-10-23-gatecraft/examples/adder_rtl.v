// Reference adder: the + operator (elaborates to a ripple-carry chain).
module adder #(parameter W = 8) (input [W-1:0] a, input [W-1:0] b, input cin,
                                  output [W-1:0] sum, output cout);
    wire [W:0] full = a + b + cin;
    assign sum  = full[W-1:0];
    assign cout = full[W];
endmodule
