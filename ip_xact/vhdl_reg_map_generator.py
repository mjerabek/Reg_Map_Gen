################################################################################                                                     
## 
## Register map generation tool
##
## Copyright (C) 2018 Ondrej Ille <ondrej.ille@gmail.com>
##
## Permission is hereby granted, free of charge, to any person obtaining a copy
## of this SW component and associated documentation files (the "Component"),
## to deal in the Component without restriction, including without limitation
## the rights to use, copy, modify, merge, publish, distribute, sublicense,
## and/or sell copies of the Component, and to permit persons to whom the
## Component is furnished to do so, subject to the following conditions:
##
## The above copyright notice and this permission notice shall be included in
## all copies or substantial portions of the Component.
##
## THE COMPONENT IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
## IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
## FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
## AUTHORS OR COPYRIGHTHOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
## LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
## FROM, OUT OF OR IN CONNECTION WITH THE COMPONENT OR THE USE OR OTHER DEALINGS
## IN THE COMPONENT.
##
###############################################################################

###############################################################################
##
##   Register map generator. Generates synthesizable VHDL entity from IP-XACT
##   Address Map. Uses constants generated by Address map generator.
##
##	Revision history:
##		7.10.2018	First implementation
##
################################################################################

import math
import os
import sys

from abc import ABCMeta, abstractmethod
from pyXact_generator.ip_xact.addr_generator import IpXactAddrGenerator

from pyXact_generator.gen_lib import *

from pyXact_generator.languages.gen_vhdl import VhdlGenerator
from pyXact_generator.languages.declaration import LanDeclaration

class VhdlRegMapGenerator(IpXactAddrGenerator):

	vhdlGen = None

	# Paths of VHDL templates
	template_sources = {}
	template_sources["addr_dec_template_path"] = "templates/address_decoder.vhd"
	template_sources["reg_template_path"] = "templates/memory_reg.vhd"
	template_sources["data_mux_template_path"] = "templates/data_mux.vhd"
	template_sources["mem_bus_template_path"] = "templates/memory_bus.vhd"
	template_sources["access_signaller_template_path"] = "templates/access_signaler.vhd"
	template_sources["cmn_reg_map_pkg"] = "templates/cmn_reg_map_pkg.vhd"


	of_pkg = None

	def __init__(self, pyXactComp, memMap, wrdWidth):
		super().__init__(pyXactComp, memMap, wrdWidth)
		self.vhdlGen = VhdlGenerator()
	
	
	def commit_to_file(self):
		""" 
		Commit the generator output into the output file.
		"""
		for line in self.vhdlGen.out :
			self.of.write(line)

		self.vhdlGen.out = []


	def create_reg_ports(self, block, signDict):
		"""
		Creates declarations for Output/Input ports of an entity which
		correspond to values Written / Read  to / from registers. 
		Declarations have following format:
			signal <block_name>_in   : in <block_name>_in_t
			signal <block_name>_out  : in <block_name>_out_t
		Declarations are appended to signDict dictionary.
		"""
		if (not checkIsDict(signDict)):
			return
			
		reg_ports = ["out", "in"]

		for reg_port in reg_ports:
			port = LanDeclaration(block.name + "_" + reg_port, value=None)
			port.direction = reg_port
			port.type = block.name + "_" + reg_port + "_t"
			port.bitWidth = 0
			port.specifier = "signal"
			signDict[port.name] = port


	def create_wr_reg_sel_decl(self, block, signDict):
		"""
		Create declaration of register selector signal for writable
		registers within a memory block. Width of register selector is number of
		words within a block which contain at least one writable register.
		"""
		signDict["reg_sel"] = LanDeclaration("reg_sel", value = None)
		signDict["reg_sel"].type = "std_logic"
		signDict["reg_sel"].specifier = "signal"
		signDict["reg_sel"].bitWidth = self.calc_blk_wrd_count(block)


	def calc_addr_vect_value(self, block):
		"""
		Calculate address vector value for address decoder for reach register
		word.
		"""
		vect_val = ""
		addr_entry_width = self.calc_wrd_address_width(block)

		# Check if register is present on a given word, if yes, append it to the
		# vector.
		[low_addr, high_addr] = self.calc_blk_wrd_span(block)
		high_addr += self.wrdWidthByte

		for wrd_addr in range(low_addr, high_addr, self.wrdWidthByte):
			regs_in_wrd = self.get_regs_from_word(wrd_addr, block)

			# Word with no registers can be skipped, nothing is appended to
			# address vector
			if (not regs_in_wrd):
				continue;

			# Append address vector value
			shifted_val = int(wrd_addr / self.wrdWidthByte)
			vect_val = str("{:06b}".format(shifted_val)) + vect_val

		return vect_val


	def create_addr_vect_decl(self, block, signDict):
		"""
		Create declaration of Address vector constant which is an input to
		Address decoder.
		"""
		signDict["addr_vect"] = LanDeclaration("addr_vect", value = None)
		signDict["addr_vect"].type = "std_logic"
		signDict["addr_vect"].specifier = "constant"
		signDict["addr_vect"].value = self.calc_addr_vect_value(block)

		# LSBs are cut
		addr_vect_size = self.calc_blk_wrd_count(block) * \
							self.calc_wrd_address_width(block)
		signDict["addr_vect"].bitWidth = addr_vect_size


	def create_read_data_mux_in_decl(self, block, signDict):
		"""
		Create declaration of read data multiplexor input signal. Length of
		read data mux input covers the minimum necessary length to cover
		all words with readable registers.
		"""
		signDict["read_data_mux_in"] = LanDeclaration("read_data_mux_in", value = None)
		signDict["read_data_mux_in"].type = "std_logic"

		[low_addr, high_addr] = self.calc_blk_wrd_span(block, ["read"])
		high_addr += self.wrdWidthByte
		signDict["read_data_mux_in"].bitWidth = (high_addr - low_addr) * 8;
		signDict["read_data_mux_in"].specifier = "signal"


	def create_read_data_mask_n_decl(self, block, signDict):
		"""
		Create declaration of Read data mask signal for Read data multiplexor.
		"""
		signDict["read_data_mask_n"] = LanDeclaration("read_data_mask_n", value = None)
		signDict["read_data_mask_n"].type = "std_logic"
		signDict["read_data_mask_n"].bitWidth = self.wrdWidthBit
		signDict["read_data_mask_n"].specifier = "signal"


	def create_write_data_int_decl(self, block, signDict):
		"""
		Create declaration for internal record with data written to writable
		registers.
		"""
		name = block.name + "_out"
		signDict[name + "_i"] = LanDeclaration(name + "_i", value = None)
		signDict[name + "_i"].type = name + "_t"
		signDict[name + "_i"].specifier = "signal"


	def create_read_mux_ena_int_decl(self, signDict):
		"""
		Create declaration for read data multiplexor enable. This allows keeping
		or clearing read data signal after data were read.
		"""
		signDict["read_mux_ena"] = LanDeclaration("read_mux_ena", value = None)
		signDict["read_mux_ena"].type = "std_logic"
		signDict["read_mux_ena"].bitWidth = 1
		signDict["read_mux_ena"].specifier = "signal"

	
	def create_internal_decls(self, block, signDict):
		"""
		Create declarations of internal signals of architecture of register
		memory block. Following declarations are created:
			- Write selector signal for all writable registers
			- Address vector input to address decoder
			- Read data multiplexor input vector.
			- Read data mask signal from byte enable signals
            - Internal signal for output register structure
		"""
		if (not checkIsDict(signDict)):
			return;

		# Create output of address decoder
		self.create_wr_reg_sel_decl(block, signDict) 

		# Create address vector input to address decoder
		self.create_addr_vect_decl(block, signDict)

		# Create data mux input signal (long logic vector)
		self.create_read_data_mux_in_decl(block, signDict)
		
		# Create data mask signal for read multiplextor
		self.create_read_data_mask_n_decl(block, signDict)

		# Create internal signal for output register structure (output values
		# of writable registers)
		self.create_write_data_int_decl(block, signDict)

		# Create declaration of read data clear signal
		self.create_read_mux_ena_int_decl(signDict)


	def append_reg_byte_val(self, block, reg, byte_ind, read_wrd):
		"""
		Append name of a register if it is located on a given byte within a
		memory word.
		Returns:
			[pad_zeroes, read_wrd]
			pad_zeroes - If zeores should be padded instead of this register
			read_wrd   - Appended value of word value
		"""
		reg_offset = reg.addressOffset % self.wrdWidthByte
		reg_bytes = reg.size / 8

		# Register starts on given byte -> Append it
		if (reg_offset == byte_ind):
			
			# Read-write registers are fed from its own values! All other
			# register types are fed from outside of the module.
			if (self.reg_is_access_type(reg, ["read-write"])):
				appendix = "_out_i."
			else:
				appendix = "_in."

			read_wrd += (block.name + appendix + reg.name).lower()
			if (byte_ind != 0):
				read_wrd += " & "
			return [False, read_wrd]

		# Register contains this byte
		elif (reg_offset <= byte_ind <= reg_offset + reg_bytes - 1):
			return [False, read_wrd]

		return [True, read_wrd]


	def create_read_wrd_from_regs(self, regs_in_wrd, block):
		"""
		Create single read word input to read data multiplexor input. Readable
		registers are implemented. 
		"""
		read_wrd = "    "
		for byte_ind in range(self.wrdWidthByte - 1, -1, -1):

			pad_zeroes = True
			for reg in regs_in_wrd:

				# Skip registers which are not readable
				if (not (self.reg_has_access_type(reg, ["read"]))):
					continue;

				[pad_zeroes, read_wrd] = self.append_reg_byte_val(block, reg, 
											byte_ind, read_wrd)
				if (pad_zeroes == False):
					break

			# If there is no register on this byte append zeroes as read data
			if (pad_zeroes):
				read_wrd += '"' + '0' * 8 + '"'
				if (byte_ind != 0):
					read_wrd += " & "

		return read_wrd


	def create_read_data_mux_in(self, block):
		"""
		Create driver for read data multiplexor input signal. Read data
		multiplexor is a long vector with read data concatenated to
		long std_logic vector.
		"""
		self.vhdlGen.write_comment("Read data driver", gap = 2)
		self.vhdlGen.wr_line("  read_data_mux_in  <= \n")

		# Check each word in the memory block, Start from highest address
		# since highest bits in std_logic_vector correspond to highest
		# address!
		[low_addr, high_addr] = self.calc_blk_wrd_span(block, ["read"])
		high_addr += self.wrdWidthByte
		for addr in reversed(range(low_addr, high_addr, self.wrdWidthByte)):

			# Create comment with word address
			self.vhdlGen.write_comment("Adress:" + str(addr), gap=4, small=True)

			# Search for all registers which are also "read" in given word
			regs_in_wrd = self.get_regs_from_word(addr, block)
			wrd_value = self.create_read_wrd_from_regs(regs_in_wrd, block)

			self.vhdlGen.wr_line(wrd_value)

			# Append "&" or ";" to the word address
			if (addr == low_addr):
				self.vhdlGen.wr_line(";\n")
			else:
				self.vhdlGen.wr_line(" &\n")

			self.vhdlGen.wr_line("\n")


	def calc_addr_indices(self, block):
		"""
        Calculates low and high index of address vector necessary for addressing
        given memory block. Each word is addressed and LSBs of address to address
        within a word is truncated.
		"""
		addr_lind = self.calc_addr_width_from_size(self.wrdWidthByte)
		addr_hind = self.calc_addr_width_from_size(block.range) - 1 

		return [addr_hind, addr_lind]


	def create_addr_decoder(self, block):
		"""
        Create instance of address decoder for writable registers.
		"""
		path = os.path.join(ROOT_PATH, self.template_sources["addr_dec_template_path"])

		addr_dec = self.vhdlGen.load_entity_template(path)
		addr_dec.isInstance = True
		addr_dec.value = addr_dec.name.lower() + "_" + block.name.lower() + "_comp"
		addr_dec.gap = 2

		# Connect generics
		addr_dec.generics["address_width"].value = self.calc_wrd_address_width(block)
		addr_dec.generics["address_entries"].value = self.calc_blk_wrd_count(block)
		addr_dec.generics["addr_vect"].value = "ADDR_VECT"
		addr_dec.generics["registered_out"].value = "false"
		addr_dec.generics["reset_polarity"].value = "reset_polarity".upper()

		# Connect ports
		addr_dec.ports["clk_sys"].value = "clk_sys"
		addr_dec.ports["res_n"].value = "res_n"
		
		addr_indices = self.calc_addr_indices(block)
		addr_str =  "address(" + str(addr_indices[0])
		addr_str += " downto " + str(addr_indices[1]) + ")"
		addr_dec.ports["address"].value = addr_str

		addr_dec.ports["addr_dec"].value = "reg_sel"

		addr_dec.ports["enable"].value = "cs"

        # Create instance of a component
		self.vhdlGen.write_comment("Write address to One-hot decoder", gap = 4)
		self.vhdlGen.format_entity_decl(addr_dec)

		self.vhdlGen.create_comp_instance(addr_dec)


	def calc_reg_data_mask(self, reg):
		"""
		Calculates data mask of given register. Data mask contains "1" for each bit
		which is implemented in the register, "0" for each bit which is not
		implemented in a register.
		"""

        # Suppose there is no implemented register
		data_mask = ["0" for x in range(reg.size)]

        # Go through fields and mark each field which is present
		for field in sorted(reg.field, key=lambda a: a.bitOffset):
			if (field.bitWidth > 1):
				for j in range(field.bitOffset, field.bitOffset + field.bitWidth):
					data_mask[j] = "1"
			else:
				data_mask[field.bitOffset] = "1"

		# Reverse the list, since std_logic_vector has opposite order than list.
        # Concat values and surround by ""
		return '"' + ''.join(data_mask[::-1]) + '"'


	def calc_reg_rstval_mask(self, reg):
		"""
        Calculate mask or reset values for given register. Reset mask contains
        value of reset after "res_n" input is released.
		"""

        # Suppose all registers are reset to zero
		rst_mask = ["0" for x in range(reg.size)]

		# Go through fields and replace each bit index by a reset value
		for field in sorted(reg.field, key=lambda a: a.bitOffset):
			remainder = field.resets.reset.value
			for j in range(field.bitWidth):
				if (remainder % 2 == 1):
					rst_mask[field.bitOffset + j] = "1"				
				remainder = int(remainder / 2)

		# Reverse the list, since std_logic_vector has opposite order than list!
		# Concat values and surround by ""
		return '"' + ''.join(rst_mask[::-1]) + '"'


	def calc_autoclear_mask(self, reg):
		"""
		Calculate mask for autoclear feature of memory register. Bits of memory
		register marked as "clear" in "write action" will be automatically cleared
		after write (One-shot like).
		"""
		# Suppose no bit is autoclear
		autoclearMask = ["0" for x in range(reg.size)]

		# Go through register fields and mark each bit whose field has "clear" action
		# on write
		for field in sorted(reg.field, key=lambda a: a.bitOffset):
			if (field.modifiedWriteValue == "clear"):
				if (field.bitWidth > 1):
					for j in range(field.bitOffset, field.bitOffset + field.bitWidth - 1):
						autoclearMask[j] = "1"
				else:
					autoclearMask[field.bitOffset] = "1"

		# Reverse the list, since std_logic_vector has opposite order than list!
		# Concat values and surround by ""
		return '"' + ''.join(autoclearMask[::-1]) + '"'


	def calc_reg_byte_enable_vector(self, reg):
		"""
		Create byte enable vector for a register. Position of register within
		a memory word is considered.
		"""
		l_be_ind = reg.addressOffset % 4
		h_be_ind = l_be_ind + int(reg.size / 8) - 1

		be_val = "be({} downto {})".format(h_be_ind, l_be_ind)

		return be_val


	def fill_reg_inst_generics(self, reg, reg_inst):
		"""
		Fill Generic values of VHDL register instance from IP-XACT register
		object.
		"""
		reg_inst.generics["data_width"].value = reg.size
		reg_inst.generics["data_mask"].value = self.calc_reg_data_mask(reg)
		reg_inst.generics["reset_polarity"].value = "reset_polarity".upper()
		reg_inst.generics["reset_value"].value = self.calc_reg_rstval_mask(reg)
		reg_inst.generics["auto_clear"].value = self.calc_autoclear_mask(reg)


	def fill_reg_ports(self, block, reg, reg_inst):
		"""
		Fill ports for VHDL register instance from IP-XACT register object
		"""
		reg_inst.ports["clk_sys"].value = "clk_sys"
		reg_inst.ports["res_n"].value = "res_n"

		reg_value = (block.name + "_out_i." + reg.name).lower()
		reg_inst.ports["reg_value"].value = reg_value

		# Calculate data input indices within a memory word
		l_ind = (reg.addressOffset * 8) % self.wrdWidthBit
		h_ind = l_ind + reg.size - 1
		reg_inst.ports["data_in"].value = "w_data({} downto {})".format(h_ind, l_ind)
		reg_inst.ports["write"].value = "write"

		reg_sel_index = self.get_wrd_index(block, reg) - 1
		reg_inst.ports["cs"].value = "reg_sel(" + str(reg_sel_index) + ")"

		# Calculate byte enable index / indices from position of register within a
		# memory word.
		reg_inst.ports["w_be"].value = self.calc_reg_byte_enable_vector(reg)


	def create_reg_instance(self, block, reg):
		"""
		Create VHDL instance from IP-XACT register object. If "isPresent" property
        is set, parameter name is searched in IP-XACT input and it's name is used
        as generic condition for register presence.
		"""
		# Load register template path and create basic instance
		path = os.path.join(ROOT_PATH, self.template_sources["reg_template_path"])
		reg_inst = self.vhdlGen.load_entity_template(path)
		reg_inst.isInstance = True
		reg_inst.intType = "entity"
		reg_inst.value = reg.name.lower() + "_reg_comp"

		self.vhdlGen.write_comment(reg.name.upper() + " register", gap = 4)

		# Fill generics of reg map component			
		self.fill_reg_inst_generics(reg, reg_inst)

		# Fill Ports of reg map component
		self.fill_reg_ports(block, reg, reg_inst)

		# Write conditional generic expression if register isPresent property 
		# depends on IP-XACT Parameter
		if (reg.isPresent != ""):
			paramName = self.parameter_lookup(reg.isPresent)
			self.vhdlGen.create_if_generate(reg.name + "_present_gen_t",
				paramName.upper(), "true", gap=4)

		# Format register instances and print it
		self.vhdlGen.format_entity_decl(reg_inst)
		self.vhdlGen.create_comp_instance(reg_inst)

		# Pop end of generate statement determined by isPresent property. Append
		# dummy drivers for case when parameter is false
		if (reg.isPresent != ""):
			self.vhdlGen.commit_append_line(1)
			self.vhdlGen.wr_line("\n")
			self.vhdlGen.create_if_generate(reg.name + "_present_gen_f",
				paramName.upper(), "false", gap=4)

			rst_val = self.calc_reg_rstval_mask(reg)
			self.vhdlGen.create_signal_connection(
				(block.name + "_out." + reg.name).lower(), rst_val, gap = 8)

			self.vhdlGen.commit_append_line(1)
			self.vhdlGen.wr_line("\n")


	def fill_access_signaller_generics(self, reg, signaller_inst):
		"""
		Fill generics for VHDL access signaller instance from IP-XACT register
		object.
		"""
		signaller_inst.generics["reset_polarity"].value = "reset_polarity".upper()
		signaller_inst.generics["data_width"].value = reg.size

		# Read signalling capability
		if (self.is_reg_read_indicate(reg)):
			signaller_inst.generics["read_signalling"].value = True
		else:
			signaller_inst.generics["read_signalling"].value = False

		# Mark read signalling as combinational value!
		signaller_inst.generics["read_signalling_reg"].value = False

		# Write signalling capability, set signalling as registered to have
		# the signal in the same clock cycle as new data are written to the
		# register!
		if (self.is_reg_write_indicate(reg)):
			signaller_inst.generics["write_signalling"].value = True
			signaller_inst.generics["write_signalling_reg"].value = True
		else:
			signaller_inst.generics["write_signalling"].value = False
			signaller_inst.generics["write_signalling_reg"].value = False	


	def fill_access_signaller_ports(self, block, reg, signaller_inst):
		"""
		Fill ports for VHDL access signaller instance from IP-XACT register
		object.
		"""
		signaller_inst.ports["clk_sys"].value = "clk_sys"
		signaller_inst.ports["res_n"].value = "res_n"

		# Get word index from address decoder
		reg_sel_index = self.get_wrd_index(block, reg) - 1
		signaller_inst.ports["cs"].value = "reg_sel(" + str(reg_sel_index) + ")"

		# Connect memory bus signals
		signaller_inst.ports["read"].value = "read"
		signaller_inst.ports["write"].value = "write"
		signaller_inst.ports["be"].value = self.calc_reg_byte_enable_vector(reg)

		# Connect write access signalling
		wr_signal = "open"
		if (self.is_reg_write_indicate(reg)):
			wr_signal = (block.name + "_out_i." + reg.name + "_write").lower()			
		signaller_inst.ports["write_signal"].value = wr_signal

		# Connect read access signalling
		rd_signal = "open"
		if (self.is_reg_read_indicate(reg)):
			rd_signal = (block.name + "_out_i." + reg.name + "_read").lower()			
		signaller_inst.ports["read_signal"].value = rd_signal


	def create_access_signaller(self, block, reg):
		"""
		Create access signaller components for registers which have this feature
		enabled.
		"""
		path = os.path.join(ROOT_PATH, self.template_sources["access_signaller_template_path"])
		signaller_inst = self.vhdlGen.load_entity_template(path)
		signaller_inst.isInstance = True
		signaller_inst.intType = "entity"
		signaller_inst.value = reg.name.lower() + "_access_signaller_comp"

		# Fill generic values of access signaller
		self.fill_access_signaller_generics(reg, signaller_inst)

		# Fill ports of access signaller
		self.fill_access_signaller_ports(block, reg, signaller_inst)

		self.vhdlGen.write_comment(reg.name.upper() + " access signallization", gap = 4)
		
		# Create component of signaller
		self.vhdlGen.format_entity_decl(signaller_inst)
		self.vhdlGen.create_comp_instance(signaller_inst)


	def create_write_reg_instances(self, block):
		"""
		Create VHDL instance for each writable register in a memory block.
		"""
		for i,reg in enumerate(sorted(block.register, key=lambda a: a.addressOffset)):

			# Create register instances for writable registers
			if (self.reg_has_access_type(reg, ["write"])):
				self.create_reg_instance(block, reg)

			# Create access signalling for registers which have signalling enabled
			if (self.is_reg_write_indicate(reg) or self.is_reg_read_indicate(reg)):
				self.create_access_signaller(block, reg)


	def create_read_data_mux_instance(self, block):
		"""
        Create instance of Read data multiplexor.
		"""
		path = os.path.join(ROOT_PATH, self.template_sources["data_mux_template_path"])

		# Load data mux template
		data_mux = self.vhdlGen.load_entity_template(path)
		data_mux.isInstance = True
		data_mux.value = (data_mux.name + "_"+ block.name + "_comp").lower()
		
		# FIll generic values
		data_mux.generics["data_out_width"].value = self.wrdWidthBit

		[low_addr, high_addr] = self.calc_blk_wrd_span(block, ["read"])
		high_addr += self.wrdWidthByte
		data_mux.generics["data_in_width"].value = (high_addr - low_addr) * 8;

		data_mux_indices = self.calc_addr_indices(block)
		data_mux_sel_width = data_mux_indices[0] - data_mux_indices[1] + 1 
		data_mux.generics["sel_width"].value = data_mux_sel_width

		data_mux.generics["registered_out"].value = "registered_read".upper()
		data_mux.generics["reset_polarity"].value = "reset_polarity".upper()

		# Connect ports
		data_mux.ports["clk_sys"].value = "clk_sys"
		data_mux.ports["res_n"].value = "res_n"

		addr_indices = self.calc_addr_indices(block)
		addr_str = "address(" + str(addr_indices[0]) + " downto " + str(addr_indices[1]) + ")"
		data_mux.ports["data_selector"].value = addr_str

		data_mux.ports["data_in"].value = "read_data_mux_in"
		data_mux.ports["data_mask_n"].value = "read_data_mask_n"
		data_mux.ports["data_out"].value = "r_data"

		# Enable data loading
		data_mux.ports["enable"].value = "read_mux_ena";

		self.vhdlGen.write_comment("Read data multiplexor", gap=4)
		self.vhdlGen.format_entity_decl(data_mux)
		self.vhdlGen.create_comp_instance(data_mux)


	def create_read_data_mask_driver(self):
		"""
		Create driver for read data mask signal from byte enable inputs of memory
		bus.
		"""
		self.vhdlGen.write_comment("Read data mask - Byte enables", gap = 4)
		self.vhdlGen.wr_line("    read_data_mask_n  <= \n")

		for byte in range(self.wrdWidthByte - 1, -1, -1):
			be_byte_str = "      " + "be({}) & ".format(byte) * 7 + "be({})".format(byte)
			self.vhdlGen.wr_line(be_byte_str)
			if (byte == 0):
				self.vhdlGen.wr_line(";\n")
			else:
				self.vhdlGen.wr_line(" &\n")

		self.vhdlGen.wr_line("\n")


	def create_reg_cond_generics(self, block, entity):
		"""
		Add conditional generic definitions into entity declaration. Parameter
		"isPresent" of each IP-XACT register is added as generic boolean input.
		Parameter look-up is performed for each found parameter.
		"""
		for reg in block.register:
			if (reg.isPresent != ""):
				paramName = self.parameter_lookup(reg.isPresent)
				entity.generics[paramName] = LanDeclaration(paramName, value = 0)
				entity.generics[paramName].value = "true"
				entity.generics[paramName].type = "boolean"
				entity.generics[paramName].specifier = "constant"


	def create_reg_block_template(self, block):
		"""
		Load memory bus entity template, add ports for register inputs, outputs.
		Create declaration of register block entity.
		"""
		# Load memory bus template and create entity definition
		path = os.path.join(ROOT_PATH, self.template_sources["mem_bus_template_path"])
		entity = self.vhdlGen.load_entity_template(path)
		entity.intType = "entity"
		entity.isInstance = False		
		entity.name = block.name.lower() + "_reg_map"

		# Add ports for register values
		self.create_reg_ports(block, entity.ports)

		# Add generics for conditionally defined components
		self.create_reg_cond_generics(block, entity)

		# Format entity declarations to look nice
		self.vhdlGen.format_decls(entity.ports, gap=2, alignLeft=True,
					alignRight=False, alignLen=30, wrap=False)
		self.vhdlGen.format_decls(entity.generics, gap=2, alignLeft=True,
					alignRight=False, alignLen=30, wrap=False)

		self.vhdlGen.create_comp_instance(entity)
		self.vhdlGen.commit_append_line(1)

		return entity


	def create_write_reg_record_driver(self, block):
		"""
		Create driver for write registe record. Internal signal is connected
		to output port.
		"""
		dest = block.name + "_out"
		src = dest + "_i"
		self.vhdlGen.create_signal_connection(dest, src, gap = 4)


	def create_psl_cover_point(self, block, reg, acc_type):
		"""
		Create PSL cover point for write into a register.
		"""
		# Get index of memory word for the register
		reg_sel_index = self.get_wrd_index(block, reg) - 1

		# Calcuate byte enable indices
		l_be_ind = reg.addressOffset % 4
		h_be_ind = l_be_ind + int(reg.size / 8) - 1
		be_str = "("
		for i in range(l_be_ind, h_be_ind + 1):
			be_str += "be({}) = '1'".format(i)
			if (i != h_be_ind):
				be_str += " or "
			else:
				be_str += ")"

		self.vhdlGen.write_comment(" psl {}_{}_access_cov : cover (".format(
			reg.name.lower(), acc_type), gap = 4, small=True)
		self.vhdlGen.write_comment("    cs = '1' and {} = '1' " \
			"and reg_sel({}) = '1' and ".format(acc_type, reg_sel_index),
			gap=4, small=True)

		self.vhdlGen.write_comment("    {});".format(be_str), gap=4, small=True)
		self.vhdlGen.wr_nl()


	def create_psl_cover_points(self, block):
		"""
		Create PSL cover points to monitor functional coverage within the
		generated block. Following points are created:
			1. Write cover point for each writable register.
			2. Read cover point for each readable register.
		"""
		# Add functional coverage comment
		self.vhdlGen.write_comment("PSL functional coverage", gap = 4)
		
		# Specify clock for PSL
		self.vhdlGen.write_comment(" psl default clock is " \
			"rising_edge(clk_sys);", gap = 4, small=True)

		# Go through the registers
		for i,reg in enumerate(sorted(block.register, key=lambda a: a.addressOffset)):

			# Create write psl coverage for every writable register
			if (self.reg_has_access_type(reg, ["write"])):
				self.create_psl_cover_point(block, reg, "write");

			# Create read psl coverage for every readable register
			if (self.reg_has_access_type(reg, ["read"])):
				self.create_psl_cover_point(block, reg, "read");


	def create_read_data_mux_ena(self):
		"""
		Create driver for read data multiplexor enable signal. If read data
		should be cleared after transaction, enable is constantly at logic 1,
		thus next cycle will data will be cleared, read mux  output flop is
		permanently enabled. If read data should not be cleared, flop is
		enabled only by new transaction.
		"""

		self.vhdlGen.write_comment("Read data multiplexor enable ", gap = 4)
		
		# Read data should be kept, enable is driven by read signal which is
		# active for each read transaction
		self.vhdlGen.create_if_generate(name="read_data_keep_gen",
				condition="clear_read_data".upper(), value="false", gap = 4)

		self.vhdlGen.create_signal_connection(result="read_mux_ena", 
												driver="read and cs", gap=8)

		self.vhdlGen.commit_append_line(1)
		self.vhdlGen.wr_line("\n")

		# Read data should be cleared, enable is constant 1, thus at next cycle
		# all byte enables will be zero and all zeroes will propagate on
		# outputs.
		self.vhdlGen.create_if_generate(name="read_data_clear_gen",
				condition="clear_read_data".upper(), value="true", gap = 4)

		# Note that this approach will clock register value to the data mux
		# output also when write is executed to this register. We don't
		# mind this, since register reads has no side effects! Side effects
		# are implemented via access_signallers and thus choosing the
		# register value by read data mux even when it is not needed is
		# sth we don't mind.
		self.vhdlGen.create_signal_connection(result="read_mux_ena",
												driver="'1'", gap=8)

		self.vhdlGen.commit_append_line(1)
		self.vhdlGen.wr_line("\n")

	def write_reg_block(self, block):
		"""
        Create register block in VHDL from IP-XACT memory block object.
		"""

		# Write file introduction
		self.vhdlGen.wr_nl()

		self.vhdlGen.write_comment("Register map implementation of: " +
				block.name, gap = 0)
		self.vhdlGen.write_gen_note()
		self.vhdlGen.wr_nl()

		self.vhdlGen.create_includes("ieee", ["std_logic_1164.all"])
		self.vhdlGen.wr_nl()

		wrk_pkgs = [self.memMap.name.lower() + "_pkg.all", "cmn_reg_map_pkg.all"]
		self.vhdlGen.create_includes("work", wrk_pkgs)

		# Create entity definition
		entity = self.create_reg_block_template(block)

		# Create architecture of Register Block
		architecture = LanDeclaration("rtl", entity.name)
		architecture.intType = "architecture"
		intSignals = {}
		architecture.ports = intSignals

		# Write declaration of internal architecture signals
		self.create_internal_decls(block, intSignals)

		# Start architecture
		self.vhdlGen.create_comp_instance(architecture)
		
		# Create instance of write address generator
		self.create_addr_decoder(block)

		# Create instance of registers
		self.create_write_reg_instances(block)

		# Create driver for enable signal for read data multiplexor
		self.create_read_data_mux_ena()

		# Create Data multiplexor for data reads
		self.create_read_data_mux_instance(block)

		# Create Driver for read data signal
		self.create_read_data_mux_in(block)
		self.create_read_data_mask_driver()

		# Create connections of internal write register record to output
		self.create_write_reg_record_driver(block)	
		self.vhdlGen.wr_line("\n")

		# Create PSL functional coverage entries
		self.create_psl_cover_points(block)

		self.vhdlGen.wr_line("\n")
		self.vhdlGen.commit_append_line(1)


	def create_output_reg_record(self, block):
		"""
		Create VHDL record for writable registers from IP-XACT memory block object.
		If register write should be indicated, additional <reg_name>_write signal
		is added.
		If register read should be indicated, additional <reg_name>_read signal is
		added.
		"""
		outDecls = []
		outName = block.name + "_out_t"

		# Create the declarations
		for i,reg in enumerate(sorted(block.register, key=lambda a: a.addressOffset)):

			if ("write" in reg.access):
				outDecls.append(LanDeclaration(reg.name, value=""))
				outDecls[-1].type = "std_logic_vector"
				outDecls[-1].bitWidth = reg.size
				outDecls[-1].specifier = ""

			if (self.is_reg_write_indicate(reg)):
				outDecls.append(LanDeclaration(reg.name + "_update", value=""))
				outDecls[-1].type = "std_logic"
				outDecls[-1].bitWidth = 1
				outDecls[-1].specifier = ""

			if (self.is_reg_read_indicate(reg)):
				outDecls.append(LanDeclaration(reg.name + "_read", value=""))
				outDecls[-1].type = "std_logic"
				outDecls[-1].bitWidth = 1
				outDecls[-1].specifier = ""

		# Format the declaration
		self.vhdlGen.format_decls(outDecls, gap=2, alignLeft=True,
					alignRight=False, alignLen=30, wrap=False)

		self.vhdlGen.create_structure(outName, outDecls, gap = 2)


	def create_input_reg_record(self, block):
		"""
		Create VHDL record for readable registers from IP-XACT memory block object.
		"""
		# Input Declarations record
		inDecls = []
		inName = block.name + "_in_t"

		for i,reg in enumerate(sorted(block.register, key=lambda a: a.addressOffset)):

			# All registers with read, but not read-write, since read-write is register
			# whose value is written and the same value is read back
			if (("read" in reg.access) and (reg.access != "read-write")):
				inDecls.append(LanDeclaration(reg.name, value=""))
				inDecls[-1].type = "std_logic_vector"
				inDecls[-1].bitWidth = reg.size
				inDecls[-1].specifier = ""

		# Format the declaration
		self.vhdlGen.format_decls(inDecls, gap=2, alignLeft=True,
					alignRight=False, alignLen=30, wrap=False)

		self.vhdlGen.create_structure(inName, inDecls, gap = 2)


	def create_mem_block_records(self, block):
		"""
		Create VHDL records for register module input/outputs. Each writable
		register is present in "write record". Each readable register is 
		present in a read record.
		"""
		self.vhdlGen.wr_nl()

		self.create_output_reg_record(block)

		self.vhdlGen.wr_nl()
		self.vhdlGen.wr_nl()

		self.create_input_reg_record(block)

		self.vhdlGen.wr_nl()


	def write_reg_map_pkg(self):
		"""
		Create package with declarations of register map input / output
		records.
		"""
		self.vhdlGen.wr_nl()

		self.vhdlGen.write_comment("Register map package for: " +
				self.memMap.name, gap = 0)
		self.vhdlGen.write_gen_note()
		self.vhdlGen.wr_nl()

		self.vhdlGen.create_includes("ieee", ["std_logic_1164.all"])
		self.vhdlGen.wr_nl()

		self.vhdlGen.create_package(self.memMap.name.lower() + "_pkg")

		for block in self.memMap.addressBlock:

			# Skip blocks marked as memory
			if (block.usage == "memory"):
				continue

			self.create_mem_block_records(block)

		self.vhdlGen.commit_append_line(1)


