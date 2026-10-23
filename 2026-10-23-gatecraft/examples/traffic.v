// Two-way traffic light controller with parametrised phase lengths.
module traffic #(parameter GREEN = 6, parameter YELLOW = 2) (
    input clk, input rst,
    output ns_green, output ns_yellow, output ns_red,
    output ew_green, output ew_yellow, output ew_red
);
    localparam W = $clog2(GREEN + 1);
    reg [1:0] phase;                 // 0: NS green, 1: NS yellow, 2: EW green, 3: EW yellow
    reg [W-1:0] timer;
    wire last = (phase[0] == 1'b0) ? (timer == GREEN - 1) : (timer == YELLOW - 1);

    always @(posedge clk) begin
        if (rst) begin phase <= 2'd0; timer <= 0; end
        else if (last) begin phase <= phase + 2'd1; timer <= 0; end
        else timer <= timer + 1'b1;
    end

    assign ns_green  = (phase == 2'd0);
    assign ns_yellow = (phase == 2'd1);
    assign ns_red    = (phase[1] == 1'b1);
    assign ew_green  = (phase == 2'd2);
    assign ew_yellow = (phase == 2'd3);
    assign ew_red    = (phase[1] == 1'b0);

    no_crash:     assert property (!(ns_green && ew_green) && !(ns_green && ew_yellow) && !(ns_yellow && ew_green));
    one_hot_ns:   assert property ((ns_green + ns_yellow + ns_red) == 1);
    timer_bounded: assert property (timer < GREEN);
endmodule
