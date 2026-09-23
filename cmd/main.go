package main

import (
	"os"

	"github.com/lindsay-cheng/ferry/internal/cli"
)

func main() {
	os.Exit(cli.Main(os.Args[1:]))
}
