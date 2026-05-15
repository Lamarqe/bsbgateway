from datetime import datetime
import os
import tempfile
from pycparser.c_ast import Constant, Decl, FileAST, ID, InitList, BinaryOp
import json
import pycparser

g_AST: FileAST

c_src = """
#include <inttypes.h>
#define MAX_HEATINGTBL 500
#define DEFAULT_FLAG FL_SW_CTL_RONLY
#include "BSB_LAN_defs.h"
"""

def get_c_variable(var_name: str):
    for ext in g_AST.ext:
        if ext.name == var_name:
            return ext
    return None

def get_string(c_var: Decl) -> str:
  val = c_var.value
  if val.startswith('\"') and val.endswith('\"'):
    return val[1:-1]  # Remove surrounding quotes

def convert_flags(flags: int) -> list[str]:
  if (isinstance(flags, Constant)):
    int_flag = int(flags.value)
    match int_flag:
      case 1:    # FL_RONLY
        return ["READONLY"]
      case 2:    # FL_WONLY
        return ["WRITEONLY"]
      case 8:    # FL_OEM
        return ["OEM_ONLY"]
      case 16:   # FL_SPECIAL_INF
        return ["SPECIAL_INF"]
      case 128:  # DEFAULT flag, aka FL_SW_CTL_RONLY
        return ["SW_CTL_RONLY"]
      case _:
        print("Unsupported flag format")
        return []
  elif (isinstance(flags, BinaryOp)) and flags.op == '+':
    return convert_flags(flags.left) + convert_flags(flags.right)
  else:
    print("Unsupported flag format")
    return []

def get_enum(enumstr):
    enum_to_decode = enumstr.init.exprs[0].value
    enum_to_decode = get_string(enumstr.init.exprs[0])
    enum_values = enum_to_decode.split('\\0')
    enum_dict = {}
    for enum_value in enum_values:
      key_str, value = enum_value.split(' ', 1)
      if key_str.startswith('\\x'):
          key = int("0x" + key_str.replace('\\x', ''), 16)
      else:
          key = int(key_str)
      enum_dict[str(key)] = { "DE": value }
    return enum_dict

def create_command(line, cmd, desc, flags) -> dict:
    command: dict = {"typename": "ENUM"}
    command["parameter"] = int(line.value) if line.type == "int" else float(line.value)
    command["command"] = cmd.value
    command["description"] = get_string(get_c_variable(desc.name).init)
    command["flags"] = convert_flags(flags)    
    return command

def main():
    with tempfile.NamedTemporaryFile() as fp:
        fp.write(c_src.encode('utf-8'))
        fp.seek(0)
        global g_AST
        home_dir = os.environ.get('HOME')
        g_AST = pycparser.parse_file(fp.name, use_cpp=True, cpp_args= [r'-I' + home_dir + '/BSB-LAN/BSB_LAN',r'-I/usr/share/python3-pycparser/fake_libc_include'])
        all_types = json.loads(open('devices/all_types.json').read())
        supported_cmd_types = {}
        for cmd in all_types["categories"]["100"]["commands"]:
            supported_cmd_types[cmd["typename"]] = cmd
            
        cmdtbl = get_c_variable("cmdtbl")
        if not isinstance(cmdtbl, Decl) or cmdtbl.name != "cmdtbl":
            print("cmdtbl not found or not a Decl")
            return

        c_command: InitList # cmd_t
        bsb_commands = []
        for c_command in cmdtbl.init.exprs:
            cmd: Constant = c_command.exprs[0]         # uint32_t cmd;         // the command or fieldID
            type: ID = c_command.exprs[1]              # uint8_t type;         // the message type
            line: Constant = c_command.exprs[2]        # float line;           // parameter number
            desc: ID = c_command.exprs[3]              # const char *desc;     // description test
            # enumstr_len: Constant = c_command.exprs[4] # uint16_t enumstr_len; // sizeof enum
            enumstr: Constant = c_command.exprs[5]     # const char *enumstr;  // enum string
            flags: Constant = c_command.exprs[6]       # uint32_t flags;       // e.g. FL_RONLY
            # dev_fam: Constant = c_command.exprs[7]     # uint8_t dev_fam;      // device family
            # dev_var: Constant = c_command.exprs[8]     # uint8_t dev_var;      // device variant
            if type.name[3:] not in supported_cmd_types:
                print(f"Unsupported command type: {type.name[3:]}")
                continue
            try:
                if int(cmd.value, 0) == 0:
                    print("Skipping CMD_UNKNOWN")
                    continue
            except ValueError:
                print("Invalid command value")
                continue

            command: dict = create_command(line, cmd, desc, flags)
            command["typename"] = type.name[3:]

            match type.name[3:]:
              case "ENUM":
                command["enum"] = get_enum(get_c_variable(enumstr.name))
              case "TEMP":
                pass
              case _:
                print(f"Supported but not implemented command type: {type.name[3:]}")
                continue

            bsb_commands.append(command)

        device_json = {
            "version": "2.1.0",
            "compiletime": datetime.now().strftime("%Y%m%d%H%M%S"),
            "categories": {
                "1": {
                    "name": {
                      "DE": "Allgemein",
                    },
                    "min": 1,
                    "max": 65536,
                    "commands": bsb_commands
                }
            }
        }

        with open("devices/my_personal_device.json", "w") as f:
            json.dump(device_json, f, indent=4)

if __name__ == "__main__":
    main()