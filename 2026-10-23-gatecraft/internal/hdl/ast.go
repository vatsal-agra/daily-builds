package hdl

import "math/big"

// ---- expressions ----

type Expr interface{ P() Pos }

type (
	// Number literal. Width 0 means unsized.
	Number struct {
		At    Pos
		Width int
		Val   *big.Int
	}
	Ident struct {
		At   Pos
		Name string
	}
	// Index is x[i] (Lo == nil, Part == 0), x[hi:lo] (Part == ':'), x[base +: w] (Part == '+'), x[base -: w] (Part == '-').
	Index struct {
		At   Pos
		X    Expr
		Hi   Expr // index / msb / base
		Lo   Expr // lsb / width
		Part byte
	}
	Unary struct {
		At Pos
		Op string // ~ ! - + & | ^ ~& ~| ~^
		X  Expr
	}
	Binary struct {
		At   Pos
		Op   string
		L, R Expr
	}
	Ternary struct {
		At      Pos
		C, T, F Expr
	}
	Concat struct {
		At    Pos
		Parts []Expr
	}
	Repl struct {
		At    Pos
		Count Expr
		X     Expr
	}
	// Call is a system function such as $clog2(x).
	Call struct {
		At   Pos
		Name string
		Args []Expr
	}
)

func (e *Number) P() Pos  { return e.At }
func (e *Ident) P() Pos   { return e.At }
func (e *Index) P() Pos   { return e.At }
func (e *Unary) P() Pos   { return e.At }
func (e *Binary) P() Pos  { return e.At }
func (e *Ternary) P() Pos { return e.At }
func (e *Concat) P() Pos  { return e.At }
func (e *Repl) P() Pos    { return e.At }
func (e *Call) P() Pos    { return e.At }

// ---- statements ----

type Stmt interface{ SP() Pos }

type (
	Block struct {
		At    Pos
		Stmts []Stmt
	}
	Assign struct {
		At          Pos
		LHS         Expr
		RHS         Expr
		NonBlocking bool
	}
	If struct {
		At   Pos
		C    Expr
		Then Stmt
		Else Stmt // may be nil
	}
	CaseItem struct {
		Labels []Expr // empty => default
		Body   Stmt
	}
	Case struct {
		At    Pos
		Sel   Expr
		Items []CaseItem
	}
	For struct {
		At   Pos
		Init *Assign
		Cond Expr
		Step *Assign
		Body Stmt
	}
)

func (s *Block) SP() Pos  { return s.At }
func (s *Assign) SP() Pos { return s.At }
func (s *If) SP() Pos     { return s.At }
func (s *Case) SP() Pos   { return s.At }
func (s *For) SP() Pos    { return s.At }

// ---- module items ----

type Range struct {
	Hi, Lo Expr
}

type Dir int

const (
	DirNone Dir = iota
	DirInput
	DirOutput
	DirInout
)

// Decl declares a net/variable/port.
type Decl struct {
	At    Pos
	Name  string
	Dir   Dir
	IsReg bool
	IsInt bool // integer
	Rng   *Range
	Init  Expr // reg x = value
	Array *Range
}

type Param struct {
	At    Pos
	Name  string
	Value Expr
	Local bool
}

type ContAssign struct {
	At       Pos
	LHS, RHS Expr
}

type Always struct {
	At    Pos
	Comb  bool   // @(*) / @*
	Clock string // posedge clock name when !Comb
	Body  Stmt
}

type Initial struct {
	At   Pos
	Body Stmt
}

type PortConn struct {
	Name string // empty => positional
	X    Expr   // nil => unconnected
}

type ParamConn struct {
	Name string
	X    Expr
}

type Instance struct {
	At     Pos
	Module string
	Name   string
	Params []ParamConn
	Conns  []PortConn
}

type PropDecl struct {
	At     Pos
	Assume bool
	X      Expr
	Name   string
}

type Module struct {
	File      string
	At        Pos
	Name      string
	Params    []Param
	PortOrder []string
	Decls     []*Decl
	Assigns   []*ContAssign
	Always    []*Always
	Initials  []*Initial
	Insts     []*Instance
	Props     []*PropDecl
	// Items in source order is not needed beyond the above.
}

// File is a parsed source file.
type File struct {
	Name    string
	Modules []*Module
}
