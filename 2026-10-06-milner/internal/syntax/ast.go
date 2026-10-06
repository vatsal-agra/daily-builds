package syntax

// ---------- Types (surface syntax) ----------

// TyExpr is a type expression as written by the user.
type TyExpr interface{ TySpan() Span }

type (
	TyVar struct {
		Name string // without the leading quote
		Sp   Span
	}
	TyCon struct {
		Name string
		Args []TyExpr
		Sp   Span
	}
	TyArrow struct {
		From, To TyExpr
		Sp       Span
	}
	TyTuple struct {
		Elems []TyExpr
		Sp    Span
	}
)

func (t *TyVar) TySpan() Span   { return t.Sp }
func (t *TyCon) TySpan() Span   { return t.Sp }
func (t *TyArrow) TySpan() Span { return t.Sp }
func (t *TyTuple) TySpan() Span { return t.Sp }

// ---------- Patterns ----------

// Pat is a pattern.
type Pat interface{ PSpan() Span }

type (
	PWild struct{ Sp Span }
	PVar  struct {
		Name string
		Sp   Span
	}
	PInt struct {
		Val int64
		Sp  Span
	}
	PStr struct {
		Val string
		Sp  Span
	}
	PBool struct {
		Val bool
		Sp  Span
	}
	PUnit  struct{ Sp Span }
	PTuple struct {
		Elems []Pat
		Sp    Span
	}
	// PCon is a constructor pattern; Arg is nil for nullary use. Lists use "[]" and "::".
	PCon struct {
		Name string
		Arg  Pat
		Sp   Span
	}
	POr struct {
		L, R Pat
		Sp   Span
	}
	PAs struct {
		P    Pat
		Name string
		Sp   Span
	}
)

func (p *PWild) PSpan() Span  { return p.Sp }
func (p *PVar) PSpan() Span   { return p.Sp }
func (p *PInt) PSpan() Span   { return p.Sp }
func (p *PStr) PSpan() Span   { return p.Sp }
func (p *PBool) PSpan() Span  { return p.Sp }
func (p *PUnit) PSpan() Span  { return p.Sp }
func (p *PTuple) PSpan() Span { return p.Sp }
func (p *PCon) PSpan() Span   { return p.Sp }
func (p *POr) PSpan() Span    { return p.Sp }
func (p *PAs) PSpan() Span    { return p.Sp }

// ---------- Expressions ----------

// Expr is an expression.
type Expr interface{ ESpan() Span }

// Binding is one `pat = expr` of a let. For function definitions the parser has already
// desugared `let f x y = e` into Pat=PVar f, Expr=EFun.
type Binding struct {
	Pat  Pat
	Expr Expr
	Sp   Span
}

// Arm is one match arm.
type Arm struct {
	Pat   Pat
	Guard Expr // nil when absent
	Body  Expr
	Sp    Span
}

type (
	EInt struct {
		Val int64
		Sp  Span
	}
	EStr struct {
		Val string
		Sp  Span
	}
	EBool struct {
		Val bool
		Sp  Span
	}
	EUnit struct{ Sp Span }
	EVar  struct {
		Name string
		Sp   Span
	}
	// ECon is a constructor use; Arg is nil for a bare constructor.
	ECon struct {
		Name string
		Arg  Expr
		Sp   Span
	}
	EFun struct {
		Params []Pat
		Body   Expr
		Sp     Span
	}
	EApp struct {
		Fn, Arg Expr
		Sp      Span
	}
	ELet struct {
		Rec      bool
		Bindings []*Binding
		Body     Expr
		Sp       Span
	}
	EIf struct {
		Cond, Then, Else Expr
		Sp               Span
	}
	EMatch struct {
		Scrut Expr
		Arms  []*Arm
		Sp    Span
	}
	ETuple struct {
		Elems []Expr
		Sp    Span
	}
	ESeq struct {
		A, B Expr
		Sp   Span
	}
	EAnd struct {
		L, R Expr
		Sp   Span
	}
	EOr struct {
		L, R Expr
		Sp   Span
	}
	EAnnot struct {
		E  Expr
		Ty TyExpr
		Sp Span
	}
	EHole struct{ Sp Span }
)

func (e *EInt) ESpan() Span   { return e.Sp }
func (e *EStr) ESpan() Span   { return e.Sp }
func (e *EBool) ESpan() Span  { return e.Sp }
func (e *EUnit) ESpan() Span  { return e.Sp }
func (e *EVar) ESpan() Span   { return e.Sp }
func (e *ECon) ESpan() Span   { return e.Sp }
func (e *EFun) ESpan() Span   { return e.Sp }
func (e *EApp) ESpan() Span   { return e.Sp }
func (e *ELet) ESpan() Span   { return e.Sp }
func (e *EIf) ESpan() Span    { return e.Sp }
func (e *EMatch) ESpan() Span { return e.Sp }
func (e *ETuple) ESpan() Span { return e.Sp }
func (e *ESeq) ESpan() Span   { return e.Sp }
func (e *EAnd) ESpan() Span   { return e.Sp }
func (e *EOr) ESpan() Span    { return e.Sp }
func (e *EAnnot) ESpan() Span { return e.Sp }
func (e *EHole) ESpan() Span  { return e.Sp }

// ---------- Declarations ----------

// ConDecl is one constructor of a type declaration.
type ConDecl struct {
	Name string
	Args []TyExpr // empty for nullary
	Sp   Span
}

// TypeDecl is one `type 'a t = A | B of ...`.
type TypeDecl struct {
	Name   string
	Params []string
	Cons   []*ConDecl
	Sp     Span
}

// Decl is a top-level declaration.
type Decl interface{ DSpan() Span }

type (
	// DLet is `let [rec] bindings`.
	DLet struct {
		Rec      bool
		Bindings []*Binding
		Sp       Span
	}
	// DType is `type ... and ...` (a mutually-recursive group).
	DType struct {
		Types []*TypeDecl
		Sp    Span
	}
	// DExpr is a bare top-level expression.
	DExpr struct {
		E  Expr
		Sp Span
	}
)

func (d *DLet) DSpan() Span  { return d.Sp }
func (d *DType) DSpan() Span { return d.Sp }
func (d *DExpr) DSpan() Span { return d.Sp }

// PAnnot is `(p : ty)`.
type PAnnot struct {
	P  Pat
	Ty TyExpr
	Sp Span
}

func (p *PAnnot) PSpan() Span { return p.Sp }
