; ball.asm -- a single ball bouncing off all four walls.
; No input. Demonstrates: sprite drawing/erasing via XOR, boundary checks
; built from SE-based equality tests, subroutine call/return, and the
; classic "LD DT / poll DT" frame-rate throttle.
;
; V0 = scratch
; VA = ball x    VB = ball y
; VC = dx flag (0 = moving right, 1 = moving left)
; VD = dy flag (0 = moving down,  1 = moving up)

        LD VA, 30
        LD VB, 10
        LD VC, 0
        LD VD, 0
        LD I, BALL
        DRW VA, VB, 2

loop:
        CALL wait_frame
        DRW VA, VB, 2       ; erase at current position

        ; --- bounce off left/right walls ---
        SE VA, 0
        JP check_x_high
        LD VC, 0
        JP after_x_check
check_x_high:
        SE VA, 62
        JP after_x_check
        LD VC, 1
after_x_check:
        SE VC, 0
        JP dec_x
        ADD VA, 1
        JP after_x_move
dec_x:
        ADD VA, 0xFF
after_x_move:

        ; --- bounce off top/bottom walls ---
        SE VB, 0
        JP check_y_high
        LD VD, 0
        JP after_y_check
check_y_high:
        SE VB, 30
        JP after_y_check
        LD VD, 1
after_y_check:
        SE VD, 0
        JP dec_y
        ADD VB, 1
        JP after_y_move
dec_y:
        ADD VB, 0xFF
after_y_move:

        DRW VA, VB, 2       ; draw at new position
        JP loop

wait_frame:
        LD V0, 4
        LD DT, V0
wf_loop:
        LD V0, DT
        SE V0, 0
        JP wf_loop
        RET

BALL:   DB 0xC0, 0xC0
