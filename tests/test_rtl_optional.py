"""Optional direct simulation of the exact supplied Verilog, using Icarus."""
from array import array
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from omega_core import CNF, MultiplexEvaluator, self_test, uniform_assignment
from omega_model import SimBackend


@unittest.skipUnless(shutil.which("iverilog") and shutil.which("vvp"), "Icarus Verilog no esta instalado")
class DirectRTLTest(unittest.TestCase):
    def test_real_verilog_against_scheduler_transactions(self):
        backend = SimBackend()
        backend.trace = []
        self_test(backend)
        cnf = CNF(90, [array("i", range(1, 71)), array("i", [-1, -90]), array("i", [90])])
        assignment = uniform_assignment(cnf, 0)
        assignment[90] = 1
        MultiplexEvaluator(backend, cross_check=True).evaluate(cnf, assignment)
        lines = ["`timescale 1ns/1ps", "module tb;", "reg clk=0, rst_n=1; reg [7:0] ui_in=0,uio_in=0;",
                 "wire [7:0] uo_out,uio_out,uio_oe;",
                 "tt_um_omega_infinity_kaoru dut(.ui_in(ui_in),.uio_in(uio_in),.uo_out(uo_out),",
                 ".uio_out(uio_out),.uio_oe(uio_oe),.ena(1'b1),.clk(clk),.rst_n(rst_n));",
                 "task tick; begin #10;clk=1;#10;clk=0;#10;end endtask", "initial begin"]
        for block_no, (gates, targets, values) in enumerate(backend.trace):
            lines.append("ui_in=0;uio_in=0;rst_n=0;#10;tick;rst_n=1;#10;")
            for op, a, b in gates:
                lines.append(f"ui_in=8'd{op | a << 3};uio_in=8'd{3 | b << 4};tick;uio_in=8'd{1 | b << 4};#10;")
            for target, value in zip(targets, values):
                expected = 0x95 if value else 0x96
                lines.append(f"ui_in=8'd{target << 3};uio_in=1;tick;ui_in=0;uio_in=8;#10;")
                lines.append(f'if(uo_out !== 8\'d{expected}) $fatal(1,"Mismatch block {block_no}, target {target}");')
        lines += ['$display("DIRECT_RTL_PASS");$finish;end', "endmodule"]
        with tempfile.TemporaryDirectory() as directory:
            testbench = Path(directory) / "tb.v"
            binary = Path(directory) / "sim.vvp"
            testbench.write_text("\n".join(lines))
            subprocess.run(["iverilog", "-g2012", "-s", "tb", "-o", str(binary),
                            str(testbench), str(ROOT / "rtl_reference/project.v")], check=True,
                           capture_output=True, text=True, timeout=30)
            result = subprocess.run(["vvp", str(binary)], check=True, capture_output=True, text=True, timeout=30)
            self.assertIn("DIRECT_RTL_PASS", result.stdout)
