import logging
import os
import shutil
import tempfile
from zipfile import is_zipfile, ZipFile

from django import forms
from django.conf import settings
from django.db.models import Sum

from osgeo_importer.importers import VALID_EXTENSIONS
from osgeo_importer.utils import mkdir_p, sizeof_fmt, move
from osgeo_importer.validators import valid_file

from .models import UploadFile, UploadedData
from .validators import validate_inspector_can_read, validate_shapefiles_have_all_parts
from .validators import valid_file2, validate_shapefiles_have_all_parts2

USER_UPLOAD_QUOTA = getattr(settings, 'USER_UPLOAD_QUOTA', None)

logger = logging.getLogger(__name__)


class UploadFileForm(forms.Form):
    file = forms.FileField(widget=forms.ClearableFileInput(attrs={'multiple': True}))

    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(UploadFileForm, self).__init__(*args, **kwargs)

    class Meta:
        model = UploadFile
        fields = ['file']

    def clean2(self):
        # TODO: General efficiency concerns, how to handle partial upload,
        # handle gdb files properly (was not before)
        # Goal is to validate all files, handle zip files, directories,
        # and direct file uploads, including nested zip files or directories.
        # Fail as gracefully as possible, catching errors if we can and
        # proceeding with partial upload (?)
        cleaned_data = super(UploadFileForm, self).clean()
        outputdir = tempfile.mkdtemp()
        files = self.files.getlist('file')
        # The end result of this should be, everything has been written
        # to our output dir that is an acceptable & valid file
        # Similar to subdirectory recursion in clean_recursive,
        # we want to grab every file inside outputdir and place in a list
        # of cleaned_files, which then we're mostly through old clean(),
        # at the point of inspected_files as below
        # If we go with more restrictive erroring and return errors upon
        # finding problems in clean_recursive, then check them here
        # and add to self.add_error
        # If this doesn't work for modifying outputdir as I expect,
        # then unfortunately embed the function definition here and hold
        # ouptutdir in higherscope and try that
        # TODO: Does this correctly get our list of cleaned files?
        cleaned_files = clean_recursive(files, outputdir, [])
        # Assuming this has worked correctly up to this point, have cleaned_files
        inspected_files = []
        file_names = [os.path.basename(f.name) for f in cleaned_files]
        upload_size = 0
        for cleaned_file in cleaned_files:
            cleaned_file_path = os.path.join(outputdir, cleaned_file.name)
            # Now this should -always- return True or at least not hit any
            # errors because of nested zips since it won't be a nested zip
            if validate_inspector_can_read(cleaned_file_path):
                add_file = True
                name, ext = os.path.splitext(
                    os.path.basename(cleaned_file.name))
                upload_size += os.path.getsize(cleaned_file_path)

                # Copied from previous, but why is this here like this?
                # How are xmls handled?
                if ext == '.xml':
                    if '{}.shp'.format(name) in file_names:
                        add_file = False
                    elif '.shp' in name and name in file_names:
                        add_file = False

                if add_file:
                    # This is where we might be hecked up... if cleaned_files is wrong
                    if cleaned_file not in inspected_files:
                        inspected_files.append(cleaned_file)
                else:
                    logger.warning(
                        'Inspector could not read file {} or file is empty'
                        .format(cleaned_file_path))
            else:
                logger.warning(
                    'Inspector could not read file {} or file is empty'.format(
                        cleaned_file_path))

        cleaned_data['file'] = inspected_files
        cleaned_data['upload_size'] = upload_size
        # upload size/quota checks
        if USER_UPLOAD_QUOTA is not None:
            # Get the total size of all data uploaded by this user
            user_filesize = UploadedData.objects.filter(
                user=self.request.user).aggregate(s=Sum('size'))['s']
            if user_filesize is None:
                user_filesize = 0
            if user_filesize + upload_size > USER_UPLOAD_QUOTA:
                # remove temp directory used for processing upload
                # if quota exceeded
                shutil.rmtree(outputdir)
                self.add_error('file',
                               'User Quota Exceeded. Quota: {0} Used: {1} '
                               'Adding: {2}'.format(
                                sizeof_fmt(USER_UPLOAD_QUOTA),
                                sizeof_fmt(user_filesize),
                                sizeof_fmt(upload_size)))
        return cleaned_data

    # This is the one I think will work
    def clean3(self):
        # TODO: General efficiency concerns, how to handle partial upload,
        # handle gdb files properly (was not before) and xml files
        cleaned_data = super(UploadFileForm, self).clean()
        outputdir = tempfile.mkdtemp()
        files = self.files.getlist('file')
        cleaned_files = clean_files(files, outputdir)
        inspected_files = []
        file_names = [os.path.basename(f.name) for f in cleaned_files]
        upload_size = 0
        for cleaned_file in cleaned_files:
            # TODO: Handle gdb files properly?
            cleaned_file_path = os.path.join(outputdir, cleaned_file.name)
            if validate_inspector_can_read(cleaned_file_path):
                add_file = True
                name, ext = os.path.splitext(
                    os.path.basename(cleaned_file.name))
                upload_size += os.path.getsize(cleaned_file_path)

                # TODO: Check xml handling
                if ext == '.xml':
                    if '{}.shp'.format(name) in file_names:
                        add_file = False
                    elif '.shp' in name and name in file_names:
                        add_file = False

                if add_file:
                    if cleaned_file not in inspected_files:
                        inspected_files.append(cleaned_file)
                else:
                    logger.warning(
                        'Inspector could not read file {} or file is empty'
                        .format(cleaned_file_path))
            else:
                logger.warning(
                    'Inspector could not read file {} or file is empty'.format(
                        cleaned_file_path))

        cleaned_data['file'] = inspected_files
        cleaned_data['upload_size'] = upload_size
        # upload size/quota checks
        if USER_UPLOAD_QUOTA is not None:
            # Get the total size of all data uploaded by this user
            user_filesize = UploadedData.objects.filter(
                user=self.request.user).aggregate(s=Sum('size'))['s']
            if user_filesize is None:
                user_filesize = 0
            if user_filesize + upload_size > USER_UPLOAD_QUOTA:
                # remove temp directory used for processing upload
                # if quota exceeded
                shutil.rmtree(outputdir)
                self.add_error('file',
                               'User Quota Exceeded. Quota: {0} Used: {1} '
                               'Adding: {2}'.format(
                                sizeof_fmt(USER_UPLOAD_QUOTA),
                                sizeof_fmt(user_filesize),
                                sizeof_fmt(upload_size)))
        return cleaned_data

    # Things I wanna know:
    # What is the type of files? What kinda object?
    # What is the type of an opened zip file?
    # Does mkdir_p even do anything? - no...?
    def clean(self):
        cleaned_data = super(UploadFileForm, self).clean()
        outputdir = tempfile.mkdtemp()
        files = self.files.getlist('file')
        # Files that need to be processed

        process_files = []

        # Create list of all potentially valid files, exploding first level zip files
        for f in files:
            errors = valid_file(f)
            if errors != []:
                logger.warning(', '.join(errors))
                continue
            if is_zipfile(f):
                with ZipFile(f) as zip:
                    for zipname in zip.namelist():
                        zipext = zipname.split(os.extsep, 1)[-1]
                        zipext = zipext.lstrip('.').lower()
                        if zipext in VALID_EXTENSIONS:
                            process_files.append(zipname)
            else:
                process_files.append(f.name)

        # Make sure shapefiles have all their parts
        if not validate_shapefiles_have_all_parts(process_files):
            self.add_error('file', 'Shapefiles must include .shp,.dbf,.shx,.prj')

        # Unpack all zip files and create list of cleaned file objects, excluding any not in
        #    VALID_EXTENSIONS
        cleaned_files = []
        for f in files:
            if f.name in process_files:
                with open(os.path.join(outputdir, f.name), 'w') as outfile:
                    for chunk in f.chunks():
                        outfile.write(chunk)
                    # raise RuntimeError
                cleaned_files.append(outfile)
            elif is_zipfile(f):
                with ZipFile(f) as zip:
                    for zipfile in zip.namelist():
                        # When this happens is it not... zipfile/file.gdb/ and therefore skipped...?
                        # Will it recurse down into the gdb directory or what's going on here?
                        if ((zipfile in process_files or ('gdb/' in VALID_EXTENSIONS and
                                                          '{}{}'.format(os.extsep, 'gdb/') in zipfile)) and
                                not zipfile.endswith('/')):
                            with zip.open(zipfile) as zf:
                                # What is this line actually doing?
                                # outputdir has a directory for the name of the archive I guess?
                                # Not sure... this looks like it wants to create the directory
                                # /outputdir/???zipfile?
                                # What is even the point of doing this? Would everything work
                                # if I just get rid of this? Or does it break the open?
                                # Maybe this is some half finished attempt to
                                # handle file gdb? Where we should open that instead?
                                # Yes, seems we can remove mkdir_p here
                                # mkdir_p(os.path.join(outputdir, os.path.dirname(zipfile)))
                                with open(os.path.join(outputdir, zipfile), 'w') as outfile:
                                    shutil.copyfileobj(zf, outfile)
                                    cleaned_files.append(outfile)

        # After moving files in place make sure they can be opened by inspector
        inspected_files = []
        file_names = [os.path.basename(f.name) for f in cleaned_files]
        upload_size = 0

        # At this point, cleaned_files points to every file in the
        # outputdir temp dir we created and copied validated files into
        # ergo, list of pointers to good boi files
        # What we are doing here is one last inspection
        # (check importer can read the geometry and shit)
        # (check we haven't gone overboard on filesize)
        # We are for some reason skipping xml files here too???
        # are they processed somewhere or whats?
        for cleaned_file in cleaned_files:
            # What is even the difference between these two?
            # Maybe there is only a difference for gdbs I guess...
            if '{}{}'.format(os.extsep, 'gdb/') in cleaned_file.name:
                cleaned_file_path = os.path.join(outputdir, os.path.dirname(cleaned_file.name))
            else:
                cleaned_file_path = os.path.join(outputdir, cleaned_file.name)
            # Here is where we failured
            # cleaned_file_path is our full path to tmp dir/file name
            # (but NOT the file itself?)
            if validate_inspector_can_read(cleaned_file_path):
                add_file = True
                name, ext = os.path.splitext(os.path.basename(cleaned_file.name))
                upload_size += os.path.getsize(cleaned_file_path)

                if ext == '.xml':
                    if '{}.shp'.format(name) in file_names:
                        add_file = False
                    elif '.shp' in name and name in file_names:
                        add_file = False

                if add_file:
                    if cleaned_file not in inspected_files:
                        inspected_files.append(cleaned_file)
                else:
                    logger.warning('Inspector could not read file {} or file is empty'.format(cleaned_file_path))
                    continue
            else:
                logger.warning('Inspector could not read file {} or file is empty'.format(cleaned_file_path))
                continue

        cleaned_data['file'] = inspected_files
        # Get total file size
        cleaned_data['upload_size'] = upload_size
        if USER_UPLOAD_QUOTA is not None:
            # Get the total size of all data uploaded by this user
            user_filesize = UploadedData.objects.filter(user=self.request.user).aggregate(s=Sum('size'))['s']
            if user_filesize is None:
                user_filesize = 0
            if user_filesize + upload_size > USER_UPLOAD_QUOTA:
                # remove temp directory used for processing upload if quota exceeded
                shutil.rmtree(outputdir)
                self.add_error('file', 'User Quota Exceeded. Quota: %s Used: %s Adding: %s' % (
                    sizeof_fmt(USER_UPLOAD_QUOTA),
                    sizeof_fmt(user_filesize),
                    sizeof_fmt(upload_size)
                ))
        return cleaned_data


def clean_files(files, outputdir):
    """
    Clean all files and move them into outputdir
    :param files: List of uploaded files to clean and move
    :param outputdir: Name of directory to move files into
    :return: List of successfully cleaned files
    """
    errors = validate_shapefiles_have_all_parts2(files)
    if errors:
        # TODO: Should we completely error out, or just log a warning?
        logger.warning('Shapefiles must include .shp,.dbf,.shx,.prj. '
                       'Could not find all matching files for:'
                       '{0}'.format(''.join(errors)))
    cleaned_files = []
    for f in files:
        if is_zipfile(f):
            cleaned_files.extend(clean_zip(ZipFile(f), outputdir))
        else:
            validation_errors = valid_file2(f)
            if validation_errors:
                # TODO: Should we completely error out,
                # or just log a warning?
                logger.warning(validation_errors)
            else:
                try:
                    cleaned_files.append(move(f, outputdir))
                except Exception as e:
                    # TODO: Should we completely error out,
                    # or just log a warning?
                    logger.warning('Problem trying to add file {0} to {1}: {2}'
                                   .format(f.name, outputdir, e))
    return cleaned_files


def clean_zip(zipfile, outputdir):
    """
    Recursive function to clean files in a zipfile, handling nested zipfiles
    :param zipfile: The zipfile to clean & whose contents to move to outputdir
    :param outputdir: The directory to move cleaned files into
    :return: A list of cleaned files from this zipfile
    """
    cleaned_files = []
    for zn in zipfile.namelist():
        if is_zipfile(zn):
            cleaned_files.extend(clean_zip(ZipFile(zn), outputdir))
        elif os.path.isfile(zn):
            # Open the file from the zip to prepare for move into outputdir
            with zipfile.open(zn) as zf:
                cleaned_files.append(move(zf, outputdir))
        # Ignore directories because namelist() will go down into them
        else:
            continue
    return cleaned_files


# TODO: Redo this with a main clean and recursive clean_zip
# Things to test:
# Getting a list of unzipped_files[] works (and can be accessed recursively)
# Getting the list of files from a directory in the same type as we expect
def clean_recursive(files, outputdir, cleaned_files):
    # first validate all shapefiles
    errors = validate_shapefiles_have_all_parts(files)
    if errors:
        # TODO: Should we completely error out, or just log a warning?
        logger.warning('Shapefiles must include .shp,.dbf,.shx,.prj. '
                       'Could not find all matching files for:'
                       '{0}'.format(''.join(errors)))

    for f in files:
        # Zipfile case
        if is_zipfile(f):
            zipf = ZipFile(f)
            unzipped_files = []
            # TODO: Will this work to extract files and recurse?
            for zname in zipf.namelist():
                unzipped_files.append(zipf.open(zname))
            clean_recursive(unzipped_files, outputdir, cleaned_files)
        # Directory case
        elif os.path.isdir(f):
            # sub_files = [file for file in os.listdir(f)
            #             if os.path.isfile(os.path.join(f, file))]
            # TODO: Is this fine...?
            clean_recursive(os.listdir(f), outputdir, cleaned_files)
        # Normal file case
        else:
            validation_errors = valid_file(f)
            if validation_errors:
                # TODO: Should we completely error out,
                # or just log a warning?
                logger.warning(validation_errors)
            else:
                # What if we returned move_errors? Well, that does not work
                # because we are in a for loop - we wouldn't process all
                # That said - if we want to error out, this is okay actually
                # Can just check on every recursive call and if it returned
                # some error, then return again
                try:
                    cleaned_files = move(f, outputdir, cleaned_files)
                except Exception as e:
                    # TODO: Should we completely error out,
                    # or just log a warning?
                    logger.warning('Problem trying to add file {0} to {1}: {2}'
                                   .format(f.name, outputdir, e))

    return cleaned_files
