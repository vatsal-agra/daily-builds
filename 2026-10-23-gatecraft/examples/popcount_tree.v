// Population count as a balanced adder tree on bit pairs / nibbles / bytes.
module popcount (input [15:0] x, output [4:0] n);
    wire [1:0] p0 = x[0]  + x[1],  p1 = x[2]  + x[3],  p2 = x[4]  + x[5],  p3 = x[6]  + x[7];
    wire [1:0] p4 = x[8]  + x[9],  p5 = x[10] + x[11], p6 = x[12] + x[13], p7 = x[14] + x[15];
    wire [2:0] q0 = p0 + p1, q1 = p2 + p3, q2 = p4 + p5, q3 = p6 + p7;
    wire [3:0] r0 = q0 + q1, r1 = q2 + q3;
    assign n = r0 + r1;
endmodule
