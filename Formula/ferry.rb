class Ferry < Formula
  desc "Share a Claude Code session as a file"
  homepage "https://github.com/lindsay-cheng/ferry"
  license "MIT"

  # url "https://github.com/lindsay-cheng/ferry/archive/refs/tags/v0.1.0.tar.gz"
  # sha256 "..." # fill when a public git tag exists

  head "https://github.com/lindsay-cheng/ferry.git", branch: "main"

  depends_on "go" => :build

  def install
    system "go", "build", *std_go_args(ldflags: "-s -w"), "./cmd/ferry"
  end

  test do
    assert_match "ferry", shell_output("#{bin}/ferry --version")
    assert_match "export", shell_output("#{bin}/ferry help")
  end
end
