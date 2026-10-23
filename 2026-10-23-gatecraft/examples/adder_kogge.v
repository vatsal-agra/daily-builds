// Kogge-Stone parallel-prefix adder, written structurally with generate-style loops (for in always @*).
module adder #(parameter W = 8) (input [W-1:0] a, input [W-1:0] b, input cin,
                                  output [W-1:0] sum, output cout);
    // level 0 generate/propagate; cin folded in as bit -1 via an extra position
    localparam N = W + 1;
    reg [N-1:0] g0, p0;
    reg [N-1:0] g1, p1, g2, p2, g3, p3, g4, p4;
    integer i;
    always @* begin
        g0 = {a & b, cin};            // position 0 is the carry-in "generate"
        p0 = {a ^ b, 1'b0};
        // stage 1: distance 1
        for (i = 0; i < N; i = i + 1) begin
            if (i >= 1) begin g1[i] = g0[i] | (p0[i] & g0[i-1]); p1[i] = p0[i] & p0[i-1]; end
            else        begin g1[i] = g0[i];                      p1[i] = p0[i];          end
        end
        // stage 2: distance 2
        for (i = 0; i < N; i = i + 1) begin
            if (i >= 2) begin g2[i] = g1[i] | (p1[i] & g1[i-2]); p2[i] = p1[i] & p1[i-2]; end
            else        begin g2[i] = g1[i];                      p2[i] = p1[i];          end
        end
        // stage 3: distance 4
        for (i = 0; i < N; i = i + 1) begin
            if (i >= 4) begin g3[i] = g2[i] | (p2[i] & g2[i-4]); p3[i] = p2[i] & p2[i-4]; end
            else        begin g3[i] = g2[i];                      p3[i] = p2[i];          end
        end
        // stage 4: distance 8
        for (i = 0; i < N; i = i + 1) begin
            if (i >= 8) begin g4[i] = g3[i] | (p3[i] & g3[i-8]); p4[i] = p3[i] & p3[i-8]; end
            else        begin g4[i] = g3[i];                      p4[i] = p3[i];          end
        end
    end
    // g4[i] is the carry out of position i; sum bit k uses carry into position k+1 = g4[k]
    wire [W-1:0] pp = a ^ b;
    assign sum  = pp ^ g4[W-1:0];
    assign cout = g4[W];
endmodule
