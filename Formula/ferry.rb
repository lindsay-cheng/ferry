class Ferry < Formula
  include Language::Python::Virtualenv

  desc "Share a Claude Code session as a file. HTTP hub is optional."
  homepage "https://github.com/lindsay-cheng/ferry"
  license "MIT"

  # url "https://github.com/lindsay-cheng/ferry/archive/refs/tags/v0.1.0.tar.gz"
  # sha256 "..." # fill when a public git tag exists

  head "https://github.com/lindsay-cheng/ferry.git", branch: "main"

  depends_on "python@3.11"

  def install
    virtualenv_install_with_resources
  end

  test do
    assert_match "ferry", shell_output("#{bin}/ferry --version")
    assert_match "export", shell_output("#{bin}/ferry help")
  end
end
