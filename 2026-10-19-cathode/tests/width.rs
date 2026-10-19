use cathode::width::{char_width, str_width};

#[test]
fn widths_of_representative_characters() {
    for (c, w) in [
        ('a', 1), ('~', 1), (' ', 1), ('é', 1), ('ß', 1), ('€', 1), ('─', 1), ('█', 1), ('λ', 1), ('ж', 1), ('א', 1),
        ('日', 2), ('本', 2), ('あ', 2), ('ア', 2), ('한', 2), ('中', 2), ('Ａ', 2), ('！', 2), ('😀', 2), ('🚀', 2), ('🧑', 2),
        ('\u{301}', 0), ('\u{200d}', 0), ('\u{200b}', 0), ('\u{fe0f}', 0), ('\u{1160}', 0), ('\u{0e31}', 0), ('\u{20e3}', 0),
        ('\u{378}', 1), ('\u{1F1AE}', 1), ('\u{E0080}', 1), ('\u{1FAE8}', 2), ('\u{1FAF7}', 2),
        ('\u{ad}', 1), ('\u{0}', 0), ('\u{7}', 0), ('\u{1b}', 0), ('\u{7f}', 0), ('\u{85}', 0),
    ] {
        assert_eq!(char_width(c), w, "U+{:04X} {:?}", c as u32, c);
    }
}

#[test]
fn string_width_sums() {
    assert_eq!(str_width("abc"), 3);
    assert_eq!(str_width("日本語"), 6);
    assert_eq!(str_width("e\u{301}x"), 2);
    assert_eq!(str_width("a日b"), 4);
}

#[test]
fn every_code_point_has_a_defined_width_and_tables_are_sane() {
    let mut wide = 0;
    let mut zero = 0;
    for u in 0..=0x10FFFFu32 {
        if let Some(c) = char::from_u32(u) {
            match char_width(c) {
                0 => zero += 1,
                1 => {}
                2 => wide += 1,
                w => panic!("width {} for U+{:04X}", w, u),
            }
        }
    }
    assert!(wide > 100_000 && wide < 400_000, "wide count {}", wide);
    assert!(zero > 1_000, "zero count {}", zero);
}
