package core

// FerryError is a ferry-layer policy error.
type FerryError struct {
	Msg string
}

func (e *FerryError) Error() string {
	return e.Msg
}
