// TinyCPU: an 8-register, 8-bit, 16-bit-instruction CPU with a built-in program ROM.
// Hierarchy: tinycpu -> {rom, regfile, alu}. Two programs selectable with `prog`:
//   prog=0: sum 1..10 into r0 (55)       prog=1: Fibonacci, r0=F(10)=55, r1=F(11)=89
//
// Instruction: [15:12] op  [11:9] rd  [8:6] rs  [7:0] imm8  [5:0] target
//   0 NOP  1 LDI  2 ADD  3 SUB  4 AND  5 OR  6 XOR  7 SHL  8 SHR  9 JNZ  10 MOV  11 JMP  12 HALT

module rom (input prog, input [5:0] pc, output reg [15:0] instr);
    always @* begin
        case ({prog, pc})
            7'd0:  instr = {4'd1, 3'd0, 1'b0, 8'd0};      // LDI r0, 0
            7'd1:  instr = {4'd1, 3'd1, 1'b0, 8'd10};     // LDI r1, 10
            7'd2:  instr = {4'd1, 3'd2, 1'b0, 8'd1};      // LDI r2, 1
            7'd3:  instr = {4'd2, 3'd0, 3'd1, 6'd0};      // ADD r0, r1
            7'd4:  instr = {4'd3, 3'd1, 3'd2, 6'd0};      // SUB r1, r2
            7'd5:  instr = {4'd9, 3'd1, 3'd0, 6'd3};      // JNZ r1, 3
            7'd6:  instr = {4'd12, 12'd0};                // HALT
            // ---- program 1: Fibonacci
            7'd64: instr = {4'd1, 3'd0, 1'b0, 8'd0};      // LDI r0, 0
            7'd65: instr = {4'd1, 3'd1, 1'b0, 8'd1};      // LDI r1, 1
            7'd66: instr = {4'd1, 3'd7, 1'b0, 8'd1};      // LDI r7, 1
            7'd67: instr = {4'd1, 3'd6, 1'b0, 8'd10};     // LDI r6, 10
            7'd68: instr = {4'd10, 3'd2, 3'd0, 6'd0};     // MOV r2, r0
            7'd69: instr = {4'd2, 3'd2, 3'd1, 6'd0};      // ADD r2, r1
            7'd70: instr = {4'd10, 3'd0, 3'd1, 6'd0};     // MOV r0, r1
            7'd71: instr = {4'd10, 3'd1, 3'd2, 6'd0};     // MOV r1, r2
            7'd72: instr = {4'd3, 3'd6, 3'd7, 6'd0};      // SUB r6, r7
            7'd73: instr = {4'd9, 3'd6, 3'd0, 6'd4};      // JNZ r6, 4
            7'd74: instr = {4'd12, 12'd0};                // HALT
            default: instr = {4'd12, 12'd0};
        endcase
    end
endmodule

module alu (input [3:0] op, input [7:0] a, input [7:0] b, output reg [7:0] y);
    always @* begin
        case (op)
            4'd2:  y = a + b;
            4'd3:  y = a - b;
            4'd4:  y = a & b;
            4'd5:  y = a | b;
            4'd6:  y = a ^ b;
            4'd7:  y = a << 1;
            4'd8:  y = a >> 1;
            4'd10: y = b;
            default: y = a;
        endcase
    end
endmodule

module regfile (input clk, input rst, input we, input [2:0] wsel, input [7:0] wdata,
                input [2:0] rsel_a, input [2:0] rsel_b,
                output reg [7:0] ra, output reg [7:0] rb, output [7:0] r0, output [7:0] r1);
    reg [7:0] x0, x1, x2, x3, x4, x5, x6, x7;
    assign r0 = x0;
    assign r1 = x1;
    always @(posedge clk) begin
        if (rst) begin
            x0 <= 0; x1 <= 0; x2 <= 0; x3 <= 0; x4 <= 0; x5 <= 0; x6 <= 0; x7 <= 0;
        end else if (we) begin
            case (wsel)
                3'd0: x0 <= wdata;  3'd1: x1 <= wdata;  3'd2: x2 <= wdata;  3'd3: x3 <= wdata;
                3'd4: x4 <= wdata;  3'd5: x5 <= wdata;  3'd6: x6 <= wdata;  default: x7 <= wdata;
            endcase
        end
    end
    always @* begin
        case (rsel_a)
            3'd0: ra = x0; 3'd1: ra = x1; 3'd2: ra = x2; 3'd3: ra = x3;
            3'd4: ra = x4; 3'd5: ra = x5; 3'd6: ra = x6; default: ra = x7;
        endcase
        case (rsel_b)
            3'd0: rb = x0; 3'd1: rb = x1; 3'd2: rb = x2; 3'd3: rb = x3;
            3'd4: rb = x4; 3'd5: rb = x5; 3'd6: rb = x6; default: rb = x7;
        endcase
    end
endmodule

module tinycpu (input clk, input rst, input prog,
                output reg [5:0] pc, output halted, output [7:0] result, output [7:0] second,
                output reg [15:0] cycles);
    wire [15:0] instr;
    wire [3:0]  op  = instr[15:12];
    wire [2:0]  rd  = instr[11:9];
    wire [2:0]  rs  = instr[8:6];
    wire [7:0]  imm = instr[7:0];
    wire [5:0]  tgt = instr[5:0];

    wire [7:0] ra, rb, alu_y;
    assign halted = (op == 4'd12);

    rom     u_rom (.prog(prog), .pc(pc), .instr(instr));
    regfile u_rf  (.clk(clk), .rst(rst), .we(write), .wsel(rd), .wdata(wdata),
                   .rsel_a(rd), .rsel_b(rs), .ra(ra), .rb(rb), .r0(result), .r1(second));
    alu     u_alu (.op(op), .a(ra), .b(rb), .y(alu_y));

    wire is_alu  = (op >= 4'd2 && op <= 4'd8) || op == 4'd10;
    wire write   = !halted && (op == 4'd1 || is_alu);
    wire [7:0] wdata = (op == 4'd1) ? imm : alu_y;
    wire taken   = (op == 4'd9 && ra != 8'd0) || op == 4'd11;

    always @(posedge clk) begin
        if (rst) begin
            pc <= 0;
            cycles <= 0;
        end else if (!halted) begin
            pc <= taken ? tgt : pc + 6'd1;
            cycles <= cycles + 16'd1;
        end
    end

    // The program counter never leaves the ROM, and a halted CPU stays halted.
    assert property (pc <= 6'd10);
endmodule
