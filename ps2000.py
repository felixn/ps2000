#!/usr/bin/env python3

"""Controlling functions for EA-PS2000 power supply

Adapted from https://github.com/marcj71/ps2000
Modified using https://github.com/xolotl90/ps2000/blob/master/ps2000.py

"""

import argparse
import functools
import struct
import sys
import time

import serial


class ps2000(object):
    # set verbose to True to see all bytes
    verbose = False

    # defines
    PS_QUERY = 0x40
    PS_SEND = 0xC0

    # nominal values, required for all voltage and current calculations
    u_nom = 0
    i_nom = 0

    # open port upon initialization
    def __init__(self, port="/dev/ttyACM0", triple=False):
        """
        :param port: The device port your power supply is connected to.
        :param triple: Set to True if you have a Triple model. This is needed to address second channel.
        """
        # set timeout to 0.06s to guarantee minimum interval time of 50ms
        self.ser_dev = serial.Serial(port, timeout=0.06, baudrate=115200, parity=serial.PARITY_ODD)
        self.u_nom = self.get_nominal_voltage()
        self.i_nom = self.get_nominal_current()
        self.triple = triple

    # close the door behind you
    def close(self):
        self.ser_dev.close()

    def __enter__(self):
        self.set_remote(True)
        if self.triple:
            self.set_remote(True, 1)
        return self

    def __exit__(self, type, value, traceback):
        self.set_remote(False)
        if self.triple:
            self.set_remote(False, 1)
        self.close()

    # construct telegram
    @staticmethod
    def _construct(type, node, obj, data):
        telegram = bytearray()
        telegram.append(0x30 + type)  # SD (start delimiter)
        telegram.append(node)  # DN (device node)
        telegram.append(obj)  # OBJ (object)
        if len(data) > 0:  # DATA
            telegram.extend(data)
            telegram[0] += len(data) - 1  # update length

        cs = 0
        for b in telegram:
            cs += b
        telegram.append(cs >> 8)  # CS0
        telegram.append(cs & 0xFF)  # CS1 (checksum)

        return telegram

    # compare checksum with header and data in response from device
    @staticmethod
    def _check_checksum(ans):
        cs = 0
        for b in ans[0:-2]:
            cs += b
        if (ans[-2] != (cs >> 8)) or (ans[-1] != (cs & 0xFF)):
            print("ERROR: checksum mismatch")
            sys.exit(1)
        else:
            return True

    # check for errors in response from device
    @staticmethod
    def _check_error(ans):
        if ans[2] != 0xFF:
            return False

        if ans[3] == 0x00:
            # this is used as an acknowledge
            return False
        elif ans[3] == 0x03:
            print("ERROR: checksum incorrect")
        elif ans[3] == 0x04:
            print("ERROR: start delimiter incorrect")
        elif ans[3] == 0x05:
            print("ERROR: wrong address for output")
        elif ans[3] == 0x07:
            print("ERROR: object not defined")
        elif ans[3] == 0x08:
            print("ERROR: object length incorrect")
        elif ans[3] == 0x09:
            print("ERROR: access denied")
        elif ans[3] == 0x0F:
            print("ERROR: device is locked")
        elif ans[3] == 0x30:
            print("ERROR: upper limit exceeded")
        elif ans[3] == 0x31:
            print("ERROR: lower limt exceeded")

        print("answer: ", end="")
        for b in ans:
            print("%02x " % (b), end="")
        print()
        sys.exit(1)

    # send one telegram, receive and check one response
    def _transfer(self, type, node, obj, data):
        telegram = self._construct(type, node, obj, data)
        if self.verbose:
            print("* telegram: ", end="")
            for b in telegram:
                print("%02x " % (b), end="")
            print()

        # send telegram
        self.ser_dev.write(telegram)

        # receive response (always ask for more than the longest answer)
        ans = self.ser_dev.read(100)

        if self.verbose:
            print("* answer:   ", end="")
            for b in ans:
                print("%02x " % (b), end="")
            print()

        # if the answer is too short, the checksum may be missing
        if len(ans) < 5:
            print("ERROR: short answer (%d bytes received)" % len(ans))
            sys.exit(1)

        # check answer
        self._check_checksum(ans)
        self._check_error(ans)

        return ans

    # get a binary object
    def _get_binary(self, obj, node):
        ans = self._transfer(self.PS_QUERY, node, obj, "")

        return ans[3:-2]

    # set a binary object
    def _set_binary(self, obj, mask, data, node):
        ans = self._transfer(self.PS_SEND, node, obj, [mask, data])

        return ans[3:-2]

    # get a string-type object
    def _get_string(self, obj, node):
        ans = self._transfer(self.PS_QUERY, node, obj, "")

        return ans[3:-3].decode("ascii")

    # get a float-type object
    def _get_float(self, obj, node):
        ans = self._transfer(self.PS_QUERY, node, obj, "")

        return struct.unpack(">f", ans[3:-2])[0]

    # get an integer object
    def _get_integer(self, obj, node):
        ans = self._transfer(self.PS_QUERY, node, obj, "")

        return (ans[3] << 8) + ans[4]

    # set an integer object
    def _set_integer(self, obj, data, node):
        ans = self._transfer(self.PS_SEND, node, obj, [data >> 8, data & 0xFF])

        return (ans[3] << 8) + ans[4]

    #
    # public functions ##################################################
    #

    # object 0
    def get_type(self):
        return self._get_string(0, node=0)

    # object 1
    def get_serial(self):
        return self._get_string(1, node=0)

    # object 2
    def get_nominal_voltage(self, node=0):
        return self._get_float(2, node)

    # object 3
    def get_nominal_current(self, node=0):
        return self._get_float(3, node)

    # object 4
    def get_nominal_power(self, node=0):
        return self._get_float(4, node)

    # object 6
    def get_article(self, node=0):
        return self._get_string(6, node)

    # object 8
    def get_manufacturer(self, node=0):
        return self._get_string(8, node)

    # object 9
    def get_version(self, node=0):
        return self._get_string(9, node)

    # object 19
    def get_device_class(self, node=0):
        return self._get_integer(19, node)

    # object 38
    def get_OVP_threshold(self, node=0):
        v = self._get_integer(38, node=0)
        return self.u_nom * v / 25600

    def set_OVP_threshold(self, u, node=0):
        return self._set_integer(38, u, node)

    # object 39
    def get_OCP_threshold(self, node=0):
        i = self._get_integer(39, node)
        return self.i_nom * i / 25600

    def set_OCP_threshold(self, i, node=0):
        return self._set_integer(39, i, node)

    # object 50
    def get_voltage_setpoint(self, node=0):
        v = self._get_integer(50, node)
        return self.u_nom * v / 25600

    def set_voltage(self, u, node=0):
        return self._set_integer(50, int(round((u * 25600.0) / self.u_nom)), node)

    # object 51
    def get_current_setpoint(self, node=0):
        i = self._get_integer(51, node)
        return self.i_nom * i / 25600

    def set_current(self, i, node=0):
        return self._set_integer(51, int(round((i * 25600.0) / self.i_nom)), node)

    # object 54
    def get_control(self, node=0):
        ans = self._get_binary(54, node)

        control = dict()
        control["output_on"] = True if ans[1] & 0x01 else False
        control["remote"] = True if ans[0] & 0x01 else False

        return control

    def _set_control(self, mask, data, node=0):
        ans = self._set_binary(54, mask, data, node)

        # return True if command was acknowledged ("error 0")
        return ans[0] == 0xFF and ans[1] == 0x00

    def get_remote(self, node=0):
        return self.get_control(node)["remote"]

    def set_remote(self, remote=True, node=0):
        if remote:
            return self._set_control(0x10, 0x10, node)
        else:
            return self._set_control(0x10, 0x00, node)

    def set_local(self, local=True, node=0):
        return self.set_remote(not local, node)

    def get_output_on(self, node=0):
        return self.get_control(node)["output_on"]

    def set_output_on(self, on=True, node=0):
        if on:
            return self._set_control(0x01, 0x01, node)
        else:
            return self._set_control(0x01, 0x00, node)

    def set_output_off(self, off=True, node=0):
        return self.set_output_on(not off, node)

    # object 71
    def get_actual(self, print_state=False, node=0):
        ans = self._get_binary(71, node)

        actual = dict()
        actual["remote"] = True if ans[0] & 0x03 else False
        actual["local"] = not actual["remote"]
        actual["on"] = True if ans[1] & 0x01 else False
        actual["CC"] = True if ans[1] & 0x06 else False
        actual["CV"] = not actual["CC"]
        # actual['tracking'] = True if ans[1] & 0x08 else False
        actual["OVP"] = True if ans[1] & 0x10 else False
        actual["OCP"] = True if ans[1] & 0x20 else False
        actual["OPP"] = True if ans[1] & 0x40 else False
        actual["OTP"] = True if ans[1] & 0x80 else False
        actual["v"] = self.u_nom * ((ans[2] << 8) + ans[3]) / 25600
        actual["i"] = self.i_nom * ((ans[4] << 8) + ans[5]) / 25600

        if print_state:
            if actual["remote"]:
                print("remote")
            else:
                print("local")

            if actual["on"]:
                print("output on")
            else:
                print("output off")

            if actual["CC"]:
                print("constant current")
            else:
                print("constant voltage")

            # for dual/triple output only
            # if actual['tracking']:
            #     print('tracking on')
            # else:
            #     print('tracking off')

            if actual["OVP"]:
                print("over-voltage protection active")
            else:
                print("over-voltage protection inactive")

            if actual["OCP"]:
                print("over-current protection active")
            else:
                print("over-current protection inactive")

            if actual["OPP"]:
                print("over-power protection active")
            else:
                print("over-power protection inactive")

            if actual["OTP"]:
                print("over-temperature protection active")
            else:
                print("over-temperature protection inactive")

            print("actual voltage %fV" % actual["v"])
            print("actual current %fA" % actual["i"])

        return actual

    # object 72
    def get_setpoints(self, node=0):
        ans = self._get_binary(72, node)

        actual = dict()
        actual["remote"] = True if ans[0] & 0x03 else False
        actual["on"] = True if ans[1] & 0x01 else False
        actual["CC"] = True if ans[1] & 0x06 else False
        actual["OVP"] = True if ans[1] & 0x10 else False
        actual["OCP"] = True if ans[1] & 0x20 else False
        actual["OPP"] = True if ans[1] & 0x40 else False
        actual["OTP"] = True if ans[1] & 0x80 else False
        actual["v"] = self.u_nom * ((ans[2] << 8) + ans[3]) / 25600
        actual["i"] = self.i_nom * ((ans[4] << 8) + ans[5]) / 25600

        return actual


@functools.lru_cache(maxsize=1)
def check_available(port, target=["PS 2042", "PS 2342"]):
    try:
        with ps2000(port) as ps:
            for t in target:
                if t in ps.get_type():
                    return True
            return False
    except serial.serialutil.SerialException:
        return False


def print_info(ps, node):
    print("type    " + ps.get_type())
    print("serial  " + ps.get_serial())
    print("article " + ps.get_article())
    print("manuf   " + ps.get_manufacturer())
    print("version " + ps.get_version())
    print("nom. voltage %f" % ps.get_nominal_voltage())
    print("nom. current %f" % ps.get_nominal_current())
    print("nom. power   %f" % ps.get_nominal_power())
    print("class        0x%04x" % ps.get_device_class())
    print("OVP          %f" % ps.get_OVP_threshold())
    print("OCP          %f" % ps.get_OCP_threshold())
    print("control      0x%04x" % ps.set_remote(node=node))
    print("output       0x%04x" % ps.set_output_on(node=node))
    ps.get_actual(True, node)
    # print('set voltage      %f %f' % (ps.set_voltage(12.34), ps.get_voltage_setpoint()))
    # ps.get_actual(True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Control PS2000 power supply")
    parser.add_argument("-p", "--port", type=str, help="serial port to use", required=True)
    parser.add_argument("-v", "--verbose", action="store_true")
    parser.add_argument(
        "-n", "--node", type=int, help="device output node [0,1] (default=0)", default=0
    )

    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--on", help="turn on", action="store_true")
    group.add_argument("--off", help="turn off", action="store_true")
    group.add_argument("--toggle", help="toggle", action="store_true")
    group.add_argument("--info", help="toggle", action="store_true")
    args = parser.parse_args()

    # set device_triple in case a node value different to 0 is used
    if args.node != 0:
        device_triple = True
    else:
        device_triple = False

    with ps2000(args.port, device_triple) as ps:

        if args.verbose:
            print("Vset: {}".format(ps.get_voltage_setpoint(args.node)))
            print("Iset: {}".format(ps.get_current_setpoint(args.node)))
            print("Vact: {}".format(ps.get_actual(node=args.node)["v"]))
            print("Iact: {}".format(ps.get_actual(node=args.node)["i"]))

        if args.on:
            print("turning on")
            ps.set_output_on(True, args.node)
        elif args.off:
            print("turning off")
            ps.set_output_on(False, args.node)
        elif args.toggle:
            output_on = ps.get_output_on(args.node)
            if output_on:
                print("Output on -> turning off")
            else:
                print("Output off -> turning on")
            ps.set_output_on(not output_on, args.node)
        elif args.info:
            print_info(ps, args.node)

        if args.verbose:
            time.sleep(1)
            print("Vact: {}".format(ps.get_actual(node=args.node)["v"]))
            print("Iact: {}".format(ps.get_actual(node=args.node)["i"]))
