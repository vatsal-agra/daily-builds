from throttle.packet import HEADER_BYTES, Segment


def test_seq_len_pure_ack_is_zero():
    seg = Segment(seq=100, ack=1, ack_flag=True)
    assert seg.seq_len == 0


def test_seq_len_syn_consumes_one():
    seg = Segment(seq=100, ack=0, syn=True)
    assert seg.seq_len == 1


def test_seq_len_fin_consumes_one():
    seg = Segment(seq=100, ack=0, fin=True)
    assert seg.seq_len == 1


def test_seq_len_data_equals_payload():
    seg = Segment(seq=100, ack=0, payload=b"hello")
    assert seg.seq_len == 5


def test_size_bytes_includes_header():
    seg = Segment(seq=0, ack=0, payload=b"x" * 10)
    assert seg.size_bytes == HEADER_BYTES + 10


def test_clone_for_retransmit_marks_flag_and_increments_count():
    seg = Segment(seq=1, ack=0, payload=b"abc")
    r1 = seg.clone_for_retransmit()
    assert r1.is_retransmit is True
    assert r1.retransmit_count == 1
    assert r1.seq == seg.seq
    assert r1.payload == seg.payload

    r2 = r1.clone_for_retransmit()
    assert r2.retransmit_count == 2


def test_clone_does_not_mutate_original():
    seg = Segment(seq=1, ack=0, payload=b"abc")
    seg.clone_for_retransmit()
    assert seg.is_retransmit is False
    assert seg.retransmit_count == 0
