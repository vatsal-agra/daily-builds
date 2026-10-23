// 4-entry, 4-bit FIFO built from explicit registers (the subset has no memory arrays).
// Properties are proved under the environment assumption that the user never pushes
// when full or pops when empty.
module fifo4 (input clk, input rst, input push, input pop, input [3:0] din,
              output [3:0] dout, output full, output empty, output [2:0] count);
    reg [3:0] e0, e1, e2, e3;
    reg [1:0] wr, rd;
    reg [2:0] n;
    assign count = n;
    assign full  = (n == 3'd4);
    assign empty = (n == 3'd0);
    assign dout  = (rd == 2'd0) ? e0 : (rd == 2'd1) ? e1 : (rd == 2'd2) ? e2 : e3;

    wire do_push = push && !full;
    wire do_pop  = pop  && !empty;

    always @(posedge clk) begin
        if (rst) begin
            wr <= 0; rd <= 0; n <= 0;
        end else begin
            if (do_push) begin
                case (wr)
                    2'd0: e0 <= din;  2'd1: e1 <= din;  2'd2: e2 <= din;  default: e3 <= din;
                endcase
                wr <= wr + 2'd1;
            end
            if (do_pop) rd <= rd + 2'd1;
            n <= n + (do_push ? 3'd1 : 3'd0) - (do_pop ? 3'd1 : 3'd0);
        end
    end

    assume property (!(push && full));
    assume property (!(pop && empty));
    count_bounded:  assert property (n <= 3'd4);
    pointer_gap:    assert property ((wr - rd) == n[1:0]);
    flags_exclusive: assert property (!(full && empty));
endmodule
