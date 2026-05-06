{
  description = "Raylib dev env";

  inputs = {
    nixpkgs.url = "github:nixos/nixpkgs/nixos-unstable";
  };

  outputs = { self, nixpkgs, ... }:
  let
    system = "x86_64-linux";
    pkgs = import nixpkgs { inherit system; };
  in {
    devShells.${system}.default = pkgs.mkShell {
      packages = [
        pkgs.gcc
        pkgs.gnumake
        pkgs.pkg-config
        pkgs.util-linux
        pkgs.linuxPackages.cpupower
        pkgs.linuxPackages.turbostat
        pkgs.texliveSmall
        pkgs.xorg-server
        (pkgs.python3.withPackages (ps: with ps; [
          numpy
          matplotlib
          pandas
        ]))
      ];

      buildInputs = [
        pkgs.raylib
        pkgs.libGL
        pkgs.libX11
      ];

      shellHook = ''
        export LD_LIBRARY_PATH="/run/opengl-driver/lib:${pkgs.lib.makeLibraryPath [
          pkgs.raylib
          pkgs.libGL
          pkgs.libX11
        ]}:$LD_LIBRARY_PATH"
      '';
    };
  };
}
