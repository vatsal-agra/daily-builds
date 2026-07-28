; pong.asm -- two-player Pong. Player 1 (left paddle, x=2): key 1 = up,
; key 4 = down. Player 2 (right paddle, x=60): key C = up, key D = down.
; First to a visible score keeps playing (score wraps at 10 -- this is a
; demo, not a tournament bracket).
;
; Register map:
;   VA, VB       ball x, y
;   VC           ball dx flag: 0 = moving right, 1 = moving left
;   VD           ball dy flag: 0 = moving down,  1 = moving up
;   V4, V5       left paddle y, right paddle y (top edge; height 6)
;   V6, V7       left score, right score
;   V0-V3        scratch
;
; Collision is checked with the SUB/VF "compare" idiom CHIP-8 programs
; use in place of a missing less-than instruction: `SUB Va, Vb` leaves
; VF=1 (no borrow) exactly when Va >= Vb.

        LD V4, 13
        LD V5, 13
        LD V6, 0
        LD V7, 0
        LD VA, 32
        LD VB, 16
        LD VC, 0
        RND VD, 0x01
        CALL redraw_all

main_loop:
        CALL wait_frame

        ; erase ball + both paddles at their current positions
        LD I, BALL
        DRW VA, VB, 1
        LD I, PADDLE
        LD V0, 2
        DRW V0, V4, 6
        LD V0, 60
        DRW V0, V5, 6

        ; --- input ---
        LD V0, 1
        SKP V0
        JP skip_l_up
        SE V4, 0
        ADD V4, 0xFF
skip_l_up:
        LD V0, 4
        SKP V0
        JP skip_l_down
        SE V4, 26
        ADD V4, 1
skip_l_down:
        LD V0, 0xC
        SKP V0
        JP skip_r_up
        SE V5, 0
        ADD V5, 0xFF
skip_r_up:
        LD V0, 0xD
        SKP V0
        JP skip_r_down
        SE V5, 26
        ADD V5, 1
skip_r_down:

        ; --- ball x: move, bounce off a paddle, or register a miss ---
        SE VC, 1
        JP x_moving_right

x_moving_left:
        LD V0, VA
        SE V0, 3
        JP x_left_move
        ; at the left bounce column -- check vertical alignment with V4
        LD V1, VB
        SUB V1, V4
        SE VF, 1
        JP x_left_move          ; VB < V4: below paddle, no bounce
        LD V2, V4
        ADD V2, 5
        LD V1, V2
        SUB V1, VB
        SE VF, 1
        JP x_left_move          ; VB > V4+5: above paddle, no bounce
        LD VC, 0                ; aligned: bounce back to the right
        JP x_phase_done
x_left_move:
        LD V0, VA
        SE V0, 0
        JP x_left_do_move
        CALL left_miss
        JP x_phase_done
x_left_do_move:
        ADD VA, 0xFF
        JP x_phase_done

x_moving_right:
        LD V0, VA
        SE V0, 59
        JP x_right_move
        LD V1, VB
        SUB V1, V5
        SE VF, 1
        JP x_right_move         ; VB < V5: below paddle, no bounce
        LD V2, V5
        ADD V2, 5
        LD V1, V2
        SUB V1, VB
        SE VF, 1
        JP x_right_move         ; VB > V5+5: above paddle, no bounce
        LD VC, 1                ; aligned: bounce back to the left
        JP x_phase_done
x_right_move:
        LD V0, VA
        SE V0, 63
        JP x_right_do_move
        CALL right_miss
        JP x_phase_done
x_right_do_move:
        ADD VA, 1
x_phase_done:

        ; --- ball y: bounce off the top/bottom walls ---
        SE VB, 0
        JP y_check_high
        LD VD, 0
        JP y_check_done
y_check_high:
        SE VB, 31
        JP y_check_done
        LD VD, 1
y_check_done:
        SE VD, 0
        JP y_do_up
        ADD VB, 1
        JP y_move_done
y_do_up:
        ADD VB, 0xFF
y_move_done:

        ; redraw ball + both paddles at their (possibly new) positions
        LD I, BALL
        DRW VA, VB, 1
        LD I, PADDLE
        LD V0, 2
        DRW V0, V4, 6
        LD V0, 60
        DRW V0, V5, 6

        JP main_loop

; -- subroutines -----------------------------------------------------

wait_frame:
        LD V0, 2
        LD DT, V0
wf_loop:
        LD V0, DT
        SE V0, 0
        JP wf_loop
        RET

left_miss:
        ADD V7, 1
        LD V0, V7
        SE V0, 10
        JP left_miss_no_wrap
        LD V7, 0
left_miss_no_wrap:
        LD VA, 32
        LD VB, 16
        LD VC, 0
        RND VD, 0x01
        CALL redraw_all
        RET

right_miss:
        ADD V6, 1
        LD V0, V6
        SE V0, 10
        JP right_miss_no_wrap
        LD V6, 0
right_miss_no_wrap:
        LD VA, 32
        LD VB, 16
        LD VC, 1
        RND VD, 0x01
        CALL redraw_all
        RET

redraw_all:
        CLS
        LD I, BALL
        DRW VA, VB, 1
        LD I, PADDLE
        LD V0, 2
        DRW V0, V4, 6
        LD V0, 60
        DRW V0, V5, 6
        LD F, V6
        LD V0, 25
        LD V1, 1
        DRW V0, V1, 5
        LD F, V7
        LD V0, 35
        LD V1, 1
        DRW V0, V1, 5
        RET

BALL:   DB 0x80
PADDLE: DB 0x80, 0x80, 0x80, 0x80, 0x80, 0x80
